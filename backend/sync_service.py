from supabase_clients import get_client, get_supabase_url


def pull_from_production():
    """
    Copy all data from production Supabase into staging Supabase.
    Used to seed staging with current production data so you have a
    realistic starting point before making changes.
    """
    staging = get_client("staging")
    prod = get_client("production")
    results = {"members": 0, "events": 0, "points": 0, "headshots": 0, "errors": []}

    try:
        # --- Step 1: Sync members ---
        prod_members = prod.table("members").select("*").execute().data or []
        for member in prod_members:
            member_copy = {k: v for k, v in member.items() if k != 'id'}
            # Rewrite headshot URLs from production domain to staging domain
            prod_url = get_supabase_url("production")
            staging_url = get_supabase_url("staging")
            if member_copy.get('headshot_url') and prod_url:
                member_copy['headshot_url'] = member_copy['headshot_url'].replace(prod_url, staging_url)
            if member_copy.get('secondary_headshot_url') and prod_url:
                member_copy['secondary_headshot_url'] = member_copy['secondary_headshot_url'].replace(prod_url, staging_url)
            try:
                staging.table("members").upsert(member_copy, on_conflict=["netid"]).execute()
                results["members"] += 1
            except Exception as e:
                results["errors"].append(f"Member {member_copy.get('netid')}: {str(e)}")

        # --- Step 2: Sync events ---
        prod_events = prod.table("events").select("*").execute().data or []
        staging_events = staging.table("events").select("name, date").execute().data or []
        existing_events = {(e["name"], e["date"]) for e in staging_events}

        for event in prod_events:
            if (event["name"], event["date"]) in existing_events:
                continue
            event_copy = {k: v for k, v in event.items() if k != 'id'}
            try:
                staging.table("events").insert(event_copy).execute()
                results["events"] += 1
            except Exception as e:
                results["errors"].append(f"Event {event.get('name')}: {str(e)}")

        # --- Step 3: Sync points_tracking (remap member_id via netid) ---
        prod_id_to_netid = {m["id"]: m["netid"] for m in prod_members}
        staging_members = staging.table("members").select("id, netid").execute().data or []
        netid_to_staging_id = {m["netid"]: m["id"] for m in staging_members}

        prod_points = prod.table("points_tracking").select("*").execute().data or []
        for pt in prod_points:
            prod_netid = prod_id_to_netid.get(pt["member_id"])
            if not prod_netid or prod_netid not in netid_to_staging_id:
                results["errors"].append(f"Points row {pt.get('id')}: could not map member_id={pt['member_id']}")
                continue
            pt_copy = {
                "member_id": netid_to_staging_id[prod_netid],
                "points": pt["points"],
                "semester": pt["semester"],
                "reason": pt.get("reason"),
            }
            try:
                staging.table("points_tracking").insert(pt_copy).execute()
                results["points"] += 1
            except Exception as e:
                results["errors"].append(f"Points for {prod_netid}: {str(e)}")

        # --- Step 4: Sync headshot files from storage ---
        try:
            prod_files = prod.storage.from_("headshots").list("eboard")
            for file_info in prod_files:
                file_name = file_info["name"]
                file_path = f"eboard/{file_name}"
                try:
                    file_bytes = prod.storage.from_("headshots").download(file_path)
                    content_type = file_info.get("metadata", {}).get("mimetype", "image/jpeg")
                    try:
                        staging.storage.from_("headshots").upload(file_path, file_bytes, {"content-type": content_type})
                    except Exception:
                        staging.storage.from_("headshots").remove([file_path])
                        staging.storage.from_("headshots").upload(file_path, file_bytes, {"content-type": content_type})
                    results["headshots"] += 1
                except Exception as e:
                    results["errors"].append(f"Headshot {file_name}: {str(e)}")
        except Exception as e:
            results["errors"].append(f"Storage sync error: {str(e)}")

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
    """
    staging = get_client("staging")
    prod = get_client("production")
    results = {"members": 0, "events": 0, "points": 0, "headshots": 0, "errors": []}

    try:
        # --- Step 1: Sync members ---
        staging_members = staging.table("members").select("*").execute().data or []
        for member in staging_members:
            member_copy = {k: v for k, v in member.items() if k != 'id'}
            # Rewrite headshot URLs from staging domain to production domain
            staging_url = get_supabase_url("staging")
            prod_url = get_supabase_url("production")
            if member_copy.get('headshot_url') and staging_url:
                member_copy['headshot_url'] = member_copy['headshot_url'].replace(staging_url, prod_url)
            if member_copy.get('secondary_headshot_url') and staging_url:
                member_copy['secondary_headshot_url'] = member_copy['secondary_headshot_url'].replace(staging_url, prod_url)

            try:
                prod.table("members").upsert(member_copy, on_conflict=["netid"]).execute()
                results["members"] += 1
            except Exception as e:
                results["errors"].append(f"Member {member_copy.get('netid')}: {str(e)}")

        # --- Step 2: Sync events (skip duplicates by name+date) ---
        staging_events = staging.table("events").select("*").execute().data or []
        prod_events = prod.table("events").select("name, date").execute().data or []
        existing_events = {(e["name"], e["date"]) for e in prod_events}

        for event in staging_events:
            if (event["name"], event["date"]) in existing_events:
                continue
            event_copy = {k: v for k, v in event.items() if k != 'id'}
            try:
                prod.table("events").insert(event_copy).execute()
                results["events"] += 1
            except Exception as e:
                results["errors"].append(f"Event {event.get('name')}: {str(e)}")

        # --- Step 3: Sync points_tracking (remap member_id via netid) ---
        # Build staging id -> netid map
        staging_id_to_netid = {m["id"]: m["netid"] for m in staging_members}

        # Build netid -> production id map
        prod_members = prod.table("members").select("id, netid").execute().data or []
        netid_to_prod_id = {m["netid"]: m["id"] for m in prod_members}

        staging_points = staging.table("points_tracking").select("*").execute().data or []
        for pt in staging_points:
            staging_netid = staging_id_to_netid.get(pt["member_id"])
            if not staging_netid or staging_netid not in netid_to_prod_id:
                results["errors"].append(f"Points row {pt.get('id')}: could not map member_id={pt['member_id']}")
                continue
            pt_copy = {
                "member_id": netid_to_prod_id[staging_netid],
                "points": pt["points"],
                "semester": pt["semester"],
                "reason": pt.get("reason"),
            }
            try:
                prod.table("points_tracking").insert(pt_copy).execute()
                results["points"] += 1
            except Exception as e:
                results["errors"].append(f"Points for {staging_netid}: {str(e)}")

        # --- Step 4: Sync headshot files from storage ---
        try:
            staging_files = staging.storage.from_("headshots").list("eboard")
            for file_info in staging_files:
                file_name = file_info["name"]
                file_path = f"eboard/{file_name}"
                try:
                    # Download from staging
                    file_bytes = staging.storage.from_("headshots").download(file_path)
                    content_type = file_info.get("metadata", {}).get("mimetype", "image/jpeg")
                    # Upload to production (try upload, then delete+re-upload if exists)
                    try:
                        prod.storage.from_("headshots").upload(file_path, file_bytes, {"content-type": content_type})
                    except Exception:
                        prod.storage.from_("headshots").remove([file_path])
                        prod.storage.from_("headshots").upload(file_path, file_bytes, {"content-type": content_type})
                    results["headshots"] += 1
                except Exception as e:
                    results["errors"].append(f"Headshot {file_name}: {str(e)}")
        except Exception as e:
            results["errors"].append(f"Storage sync error: {str(e)}")

    except Exception as e:
        results["errors"].append(f"Sync error: {str(e)}")

    return results
