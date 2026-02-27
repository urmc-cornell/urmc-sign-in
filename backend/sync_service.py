from supabase_clients import get_client, get_supabase_url


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


def pull_from_production():
    """
    Copy all data from production Supabase into staging Supabase.

    NOTE: supabase-py v2 has a shared-header bug — two clients created
    in the same process overwrite each other's API key.  We work around
    this by reading ALL data from the source first, then creating the
    destination client to write.
    """
    results = {"members": 0, "events": 0, "points": 0, "headshots": 0, "errors": []}

    try:
        # ── Phase 1: READ everything from production ──
        prod = get_client("production")
        prod_members = prod.table("members").select("*").execute().data or []
        prod_events = prod.table("events").select("*").execute().data or []
        prod_points = prod.table("points_tracking").select("*").execute().data or []

        headshot_files = []
        try:
            prod_file_list = prod.storage.from_("headshots").list("eboard")
            for file_info in prod_file_list:
                file_name = file_info["name"]
                file_path = f"eboard/{file_name}"
                try:
                    file_bytes = prod.storage.from_("headshots").download(file_path)
                    content_type = file_info.get("metadata", {}).get("mimetype", "image/jpeg")
                    headshot_files.append((file_path, file_bytes, content_type))
                except Exception as e:
                    results["errors"].append(f"Headshot download {file_name}: {str(e)}")
        except Exception as e:
            results["errors"].append(f"Storage list error: {str(e)}")

        del prod

        # ── Phase 2: WRITE everything to staging (bulk) ──
        staging = get_client("staging")
        prod_url = get_supabase_url("production")
        staging_url = get_supabase_url("staging")

        # Step 1: Bulk upsert members
        member_copies = _rewrite_urls(prod_members, prod_url, staging_url)
        if member_copies:
            try:
                staging.table("members").upsert(member_copies, on_conflict=["netid"]).execute()
                results["members"] = len(member_copies)
            except Exception as e:
                results["errors"].append(f"Bulk member upsert: {str(e)}")

        # Step 2: Bulk insert new events
        staging_events = staging.table("events").select("name, date").execute().data or []
        existing = {(e["name"], e["date"]) for e in staging_events}
        new_events = [{k: v for k, v in ev.items() if k != 'id'}
                      for ev in prod_events if (ev["name"], ev["date"]) not in existing]
        if new_events:
            try:
                staging.table("events").insert(new_events).execute()
                results["events"] = len(new_events)
            except Exception as e:
                results["errors"].append(f"Bulk event insert: {str(e)}")

        # Step 3: Bulk insert points (remap member_id)
        staging_members = staging.table("members").select("id, netid").execute().data or []
        remapped, pt_errors = _remap_points(prod_points, prod_members, staging_members)
        results["errors"].extend(pt_errors)
        if remapped:
            try:
                staging.table("points_tracking").insert(remapped).execute()
                results["points"] = len(remapped)
            except Exception as e:
                results["errors"].append(f"Bulk points insert: {str(e)}")

        # Step 4: Upload headshot files (still one-by-one — storage API limitation)
        for file_path, file_bytes, content_type in headshot_files:
            try:
                try:
                    staging.storage.from_("headshots").upload(file_path, file_bytes, {"content-type": content_type})
                except Exception:
                    staging.storage.from_("headshots").remove([file_path])
                    staging.storage.from_("headshots").upload(file_path, file_bytes, {"content-type": content_type})
                results["headshots"] += 1
            except Exception as e:
                results["errors"].append(f"Headshot {file_path}: {str(e)}")

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
    4. Headshot files from storage

    NOTE: supabase-py v2 has a shared-header bug — two clients created
    in the same process overwrite each other's API key.  We work around
    this by reading ALL data from the source first, then creating the
    destination client to write.
    """
    results = {"members": 0, "events": 0, "points": 0, "headshots": 0, "errors": []}

    try:
        # ── Phase 1: READ everything from staging ──
        staging = get_client("staging")
        staging_members = staging.table("members").select("*").execute().data or []
        staging_events = staging.table("events").select("*").execute().data or []
        staging_points = staging.table("points_tracking").select("*").execute().data or []

        headshot_files = []
        try:
            staging_file_list = staging.storage.from_("headshots").list("eboard")
            for file_info in staging_file_list:
                file_name = file_info["name"]
                file_path = f"eboard/{file_name}"
                try:
                    file_bytes = staging.storage.from_("headshots").download(file_path)
                    content_type = file_info.get("metadata", {}).get("mimetype", "image/jpeg")
                    headshot_files.append((file_path, file_bytes, content_type))
                except Exception as e:
                    results["errors"].append(f"Headshot download {file_name}: {str(e)}")
        except Exception as e:
            results["errors"].append(f"Storage list error: {str(e)}")

        del staging

        # ── Phase 2: WRITE everything to production (bulk) ──
        prod = get_client("production")
        staging_url = get_supabase_url("staging")
        prod_url = get_supabase_url("production")

        # Step 1: Bulk upsert members
        member_copies = _rewrite_urls(staging_members, staging_url, prod_url)
        if member_copies:
            try:
                prod.table("members").upsert(member_copies, on_conflict=["netid"]).execute()
                results["members"] = len(member_copies)
            except Exception as e:
                results["errors"].append(f"Bulk member upsert: {str(e)}")

        # Step 2: Bulk insert new events
        prod_events = prod.table("events").select("name, date").execute().data or []
        existing = {(e["name"], e["date"]) for e in prod_events}
        new_events = [{k: v for k, v in ev.items() if k != 'id'}
                      for ev in staging_events if (ev["name"], ev["date"]) not in existing]
        if new_events:
            try:
                prod.table("events").insert(new_events).execute()
                results["events"] = len(new_events)
            except Exception as e:
                results["errors"].append(f"Bulk event insert: {str(e)}")

        # Step 3: Bulk insert points (remap member_id)
        prod_members = prod.table("members").select("id, netid").execute().data or []
        remapped, pt_errors = _remap_points(staging_points, staging_members, prod_members)
        results["errors"].extend(pt_errors)
        if remapped:
            try:
                prod.table("points_tracking").insert(remapped).execute()
                results["points"] = len(remapped)
            except Exception as e:
                results["errors"].append(f"Bulk points insert: {str(e)}")

        # Step 4: Upload headshot files (still one-by-one — storage API limitation)
        for file_path, file_bytes, content_type in headshot_files:
            try:
                try:
                    prod.storage.from_("headshots").upload(file_path, file_bytes, {"content-type": content_type})
                except Exception:
                    prod.storage.from_("headshots").remove([file_path])
                    prod.storage.from_("headshots").upload(file_path, file_bytes, {"content-type": content_type})
                results["headshots"] += 1
            except Exception as e:
                results["errors"].append(f"Headshot {file_path}: {str(e)}")

    except Exception as e:
        results["errors"].append(f"Sync error: {str(e)}")

    return results
