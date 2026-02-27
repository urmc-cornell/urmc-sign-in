import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from supabase_clients import get_client, get_supabase_url


def _retry(fn, max_attempts=3, base_delay=2.0):
    """Retry a callable up to max_attempts times with exponential backoff."""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_error = e
            if attempt < max_attempts:
                time.sleep(base_delay * (2 ** (attempt - 1)))
    raise last_error


def _diff_headshot_lists(src_files, dst_files):
    """Compare file lists and return src entries that are new or changed vs dst."""
    dst_index = {f["name"]: f for f in dst_files}
    changed = []
    for sf in src_files:
        name = sf["name"]
        df = dst_index.get(name)
        if df is None:
            changed.append(sf)
            continue
        if sf.get("updated_at", "") > df.get("updated_at", ""):
            changed.append(sf)
            continue
        src_size = (sf.get("metadata") or {}).get("size", -1)
        dst_size = (df.get("metadata") or {}).get("size", -2)
        if src_size != dst_size:
            changed.append(sf)
    return changed


def _rewrite_urls(members, old_url, new_url):
    """Rewrite headshot URLs from one Supabase domain to another."""
    result = []
    for member in members:
        m = {k: v for k, v in member.items() if k != 'id'}
        if m.get('headshot_url') and old_url:
            m['headshot_url'] = m['headshot_url'].replace(old_url, new_url)
        if m.get('secondary_headshot_url') and old_url:
            m['secondary_headshot_url'] = m['secondary_headshot_url'].replace(old_url, new_url)
        result.append(m)
    return result


def _remap_points(points, src_members, dst_members):
    """Remap member_id in points_tracking from source IDs to destination IDs via netid."""
    src_id_to_netid = {m["id"]: m["netid"] for m in src_members}
    netid_to_dst_id = {m["netid"]: m["id"] for m in dst_members}
    remapped = []
    errors = []
    for pt in points:
        netid = src_id_to_netid.get(pt["member_id"])
        if not netid or netid not in netid_to_dst_id:
            errors.append(f"Points row {pt.get('id')}: could not map member_id={pt['member_id']}")
            continue
        remapped.append({
            "member_id": netid_to_dst_id[netid],
            "points": pt["points"],
            "semester": pt["semester"],
            "reason": pt.get("reason"),
        })
    return remapped, errors


def _delete_all_rows(client, table_name):
    """Delete all rows from a Supabase table.
    supabase-py requires a filter on delete; we use neq against a nil UUID."""
    NIL_UUID = "00000000-0000-0000-0000-000000000000"
    client.table(table_name).delete().neq("id", NIL_UUID).execute()


def _delete_extra_headshots(client, src_file_list, dst_file_list):
    """Remove headshot files in destination that are not present in source."""
    src_names = {f["name"] for f in src_file_list}
    extras = [f"eboard/{f['name']}" for f in dst_file_list if f["name"] not in src_names]
    if extras:
        client.storage.from_("headshots").remove(extras)
    return len(extras)


def pull_from_production():
    """
    Copy all data from production Supabase into staging Supabase.

    NOTE: supabase-py v2 has a shared-header bug — two clients created
    in the same process overwrite each other's API key.  We work around
    this by reading ALL data from the source first, then creating the
    destination client to write.
    """
    results = {"members": 0, "events": 0, "points": 0, "headshots": 0, "skipped_headshots": 0, "deleted_headshots": 0, "errors": []}
    MAX_WORKERS = 8

    try:
        # ── Phase 1: READ db data + list production files ──
        prod = get_client("production")
        prod_members = prod.table("members").select("*").execute().data or []
        prod_events = prod.table("events").select("*").execute().data or []
        prod_points = prod.table("points_tracking").select("*").execute().data or []

        prod_file_list = []
        try:
            prod_file_list = prod.storage.from_("headshots").list("eboard", {"limit": 1000})
        except Exception as e:
            results["errors"].append(f"Production storage list error: {str(e)}")

        del prod

        # ── Phase 2: CLEAR destination, then INSERT source data ──
        staging = get_client("staging")
        prod_url = get_supabase_url("production")
        staging_url = get_supabase_url("staging")

        # Step 1: Delete all destination data (FK order: points first, then events, then members)
        try:
            _delete_all_rows(staging, "points_tracking")
        except Exception as e:
            results["errors"].append(f"Delete staging points_tracking: {str(e)}")

        try:
            _delete_all_rows(staging, "events")
        except Exception as e:
            results["errors"].append(f"Delete staging events: {str(e)}")

        try:
            _delete_all_rows(staging, "members")
        except Exception as e:
            results["errors"].append(f"Delete staging members: {str(e)}")

        # Step 2: Insert all members (with URL rewriting)
        member_copies = _rewrite_urls(prod_members, prod_url, staging_url)
        if member_copies:
            try:
                staging.table("members").insert(member_copies).execute()
                results["members"] = len(member_copies)
            except Exception as e:
                results["errors"].append(f"Bulk member insert: {str(e)}")

        # Step 3: Insert all events (strip id)
        event_copies = [{k: v for k, v in ev.items() if k != 'id'} for ev in prod_events]
        if event_copies:
            try:
                staging.table("events").insert(event_copies).execute()
                results["events"] = len(event_copies)
            except Exception as e:
                results["errors"].append(f"Bulk event insert: {str(e)}")

        # Step 4: Insert all points (remap member_id via netid)
        staging_members = staging.table("members").select("id, netid").execute().data or []
        remapped, pt_errors = _remap_points(prod_points, prod_members, staging_members)
        results["errors"].extend(pt_errors)
        if remapped:
            try:
                staging.table("points_tracking").insert(remapped).execute()
                results["points"] = len(remapped)
            except Exception as e:
                results["errors"].append(f"Bulk points insert: {str(e)}")

        # Step 5: Diff headshot file lists + delete extras
        staging_file_list = []
        try:
            staging_file_list = staging.storage.from_("headshots").list("eboard", {"limit": 1000})
        except Exception as e:
            results["errors"].append(f"Staging storage list error: {str(e)}")

        try:
            results["deleted_headshots"] = _delete_extra_headshots(staging, prod_file_list, staging_file_list)
        except Exception as e:
            results["errors"].append(f"Delete extra staging headshots: {str(e)}")

        changed_files = _diff_headshot_lists(prod_file_list, staging_file_list)
        results["skipped_headshots"] = len(prod_file_list) - len(changed_files)

        del staging

        if changed_files:
            # ── Phase 3: Download changed headshots from production (parallel) ──
            prod2 = get_client("production")

            def _download_one(file_info):
                name = file_info["name"]
                path = f"eboard/{name}"
                ctype = (file_info.get("metadata") or {}).get("mimetype", "image/jpeg")
                data = _retry(lambda p=path: prod2.storage.from_("headshots").download(p))
                return (path, data, ctype)

            downloaded = []
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futures = {pool.submit(_download_one, fi): fi for fi in changed_files}
                for future in as_completed(futures):
                    fi = futures[future]
                    try:
                        downloaded.append(future.result())
                    except Exception as e:
                        results["errors"].append(f"Headshot download eboard/{fi['name']}: {str(e)}")

            del prod2

            # ── Phase 4: Upload changed headshots to staging (parallel) ──
            staging2 = get_client("staging")

            def _upload_one(item):
                fpath, fbytes, content_type = item
                def _do_upload():
                    try:
                        staging2.storage.from_("headshots").upload(
                            fpath, fbytes, {"content-type": content_type, "x-upsert": "true"})
                    except Exception:
                        staging2.storage.from_("headshots").remove([fpath])
                        staging2.storage.from_("headshots").upload(
                            fpath, fbytes, {"content-type": content_type})
                _retry(_do_upload)
                return fpath

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futures = {pool.submit(_upload_one, item): item[0] for item in downloaded}
                for future in as_completed(futures):
                    path = futures[future]
                    try:
                        future.result()
                        results["headshots"] += 1
                    except Exception as e:
                        results["errors"].append(f"Headshot upload {path}: {str(e)}")

    except Exception as e:
        results["errors"].append(f"Sync error: {str(e)}")

    return results


def push_to_production():
    """
    Sync all data from staging Supabase to production Supabase.

    Order matters:
    1. Members first (because points_tracking has FK to members)
    2. Events
    3. Points tracking (needs member_id remapping)
    4. Headshot files from storage (incremental — only new/changed files)

    NOTE: supabase-py v2 has a shared-header bug — two clients created
    in the same process overwrite each other's API key.  We work around
    this by reading ALL data from the source first, then creating the
    destination client to write.
    """
    results = {"members": 0, "events": 0, "points": 0, "headshots": 0, "skipped_headshots": 0, "deleted_headshots": 0, "errors": []}
    MAX_WORKERS = 8

    try:
        # ── Phase 1: READ db data + list staging files ──
        staging = get_client("staging")
        staging_members = staging.table("members").select("*").execute().data or []
        staging_events = staging.table("events").select("*").execute().data or []
        staging_points = staging.table("points_tracking").select("*").execute().data or []

        staging_file_list = []
        try:
            staging_file_list = staging.storage.from_("headshots").list("eboard", {"limit": 1000})
        except Exception as e:
            results["errors"].append(f"Staging storage list error: {str(e)}")

        del staging

        # ── Phase 2: CLEAR destination, then INSERT source data ──
        prod = get_client("production")
        staging_url = get_supabase_url("staging")
        prod_url = get_supabase_url("production")

        # Step 1: Delete all destination data (FK order: points first, then events, then members)
        try:
            _delete_all_rows(prod, "points_tracking")
        except Exception as e:
            results["errors"].append(f"Delete production points_tracking: {str(e)}")

        try:
            _delete_all_rows(prod, "events")
        except Exception as e:
            results["errors"].append(f"Delete production events: {str(e)}")

        try:
            _delete_all_rows(prod, "members")
        except Exception as e:
            results["errors"].append(f"Delete production members: {str(e)}")

        # Step 2: Insert all members (with URL rewriting)
        member_copies = _rewrite_urls(staging_members, staging_url, prod_url)
        if member_copies:
            try:
                prod.table("members").insert(member_copies).execute()
                results["members"] = len(member_copies)
            except Exception as e:
                results["errors"].append(f"Bulk member insert: {str(e)}")

        # Step 3: Insert all events (strip id)
        event_copies = [{k: v for k, v in ev.items() if k != 'id'} for ev in staging_events]
        if event_copies:
            try:
                prod.table("events").insert(event_copies).execute()
                results["events"] = len(event_copies)
            except Exception as e:
                results["errors"].append(f"Bulk event insert: {str(e)}")

        # Step 4: Insert all points (remap member_id via netid)
        prod_members = prod.table("members").select("id, netid").execute().data or []
        remapped, pt_errors = _remap_points(staging_points, staging_members, prod_members)
        results["errors"].extend(pt_errors)
        if remapped:
            try:
                prod.table("points_tracking").insert(remapped).execute()
                results["points"] = len(remapped)
            except Exception as e:
                results["errors"].append(f"Bulk points insert: {str(e)}")

        # Step 5: Diff headshot file lists + delete extras
        prod_file_list = []
        try:
            prod_file_list = prod.storage.from_("headshots").list("eboard", {"limit": 1000})
        except Exception as e:
            results["errors"].append(f"Production storage list error: {str(e)}")

        try:
            results["deleted_headshots"] = _delete_extra_headshots(prod, staging_file_list, prod_file_list)
        except Exception as e:
            results["errors"].append(f"Delete extra production headshots: {str(e)}")

        changed_files = _diff_headshot_lists(staging_file_list, prod_file_list)
        results["skipped_headshots"] = len(staging_file_list) - len(changed_files)

        del prod

        if changed_files:
            # ── Phase 3: Download changed headshots from staging (parallel) ──
            staging2 = get_client("staging")

            def _download_one(file_info):
                name = file_info["name"]
                path = f"eboard/{name}"
                ctype = (file_info.get("metadata") or {}).get("mimetype", "image/jpeg")
                data = _retry(lambda p=path: staging2.storage.from_("headshots").download(p))
                return (path, data, ctype)

            downloaded = []
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futures = {pool.submit(_download_one, fi): fi for fi in changed_files}
                for future in as_completed(futures):
                    fi = futures[future]
                    try:
                        downloaded.append(future.result())
                    except Exception as e:
                        results["errors"].append(f"Headshot download eboard/{fi['name']}: {str(e)}")

            del staging2

            # ── Phase 4: Upload changed headshots to production (parallel) ──
            prod2 = get_client("production")

            def _upload_one(item):
                fpath, fbytes, content_type = item
                def _do_upload():
                    try:
                        prod2.storage.from_("headshots").upload(
                            fpath, fbytes, {"content-type": content_type, "x-upsert": "true"})
                    except Exception:
                        prod2.storage.from_("headshots").remove([fpath])
                        prod2.storage.from_("headshots").upload(
                            fpath, fbytes, {"content-type": content_type})
                _retry(_do_upload)
                return fpath

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futures = {pool.submit(_upload_one, item): item[0] for item in downloaded}
                for future in as_completed(futures):
                    path = futures[future]
                    try:
                        future.result()
                        results["headshots"] += 1
                    except Exception as e:
                        results["errors"].append(f"Headshot upload {path}: {str(e)}")

    except Exception as e:
        results["errors"].append(f"Sync error: {str(e)}")

    return results
