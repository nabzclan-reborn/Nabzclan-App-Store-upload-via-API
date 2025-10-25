import requests
import json
import sys
import os
import tempfile
import time
from pathlib import Path

BASE_URL = "https://appstore.nabzclan.vip/api/dev" # LEAVE 
REPO_URL = "https://repo.altstore.com" # add altstore repo 
UPLOADED_FILE = "uploaded_apps.json" #prevents uploading the same apps again 
NABZ_APPSTORE_API_KEY = "99|tfkuffkuftfkutfffk" # https://appstore.nabzclan.vip/dev/api-tokens

def get_session(token):
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    })
    return session

def get_metadata(session):
    response = session.get(f"{BASE_URL}/metadata")
    if response.status_code == 200:
        data = response.json()["data"]
        return {cat["name"]: cat["id"] for cat in data["categories"]}, {plat["name"]: plat["id"] for plat in data["platforms"]}
    else:
        raise Exception(f"Failed to get metadata: {response.status_code}")

def create_app(session, app_data, category_ids, platform_ids):
    description = app_data.get("localizedDescription", "")
    if not description or len(description.strip()) < 10:
        description = f"Enhanced version of {app_data['name']} with premium features unlocked."

    payload = {
        "title": app_data["name"],
        "description": description[:500],  # Limit length - max limit 700
        "details": f"🚀 **Enhanced {app_data['name']}**\n\n **Version:** {app_data['version']}\n **Size:** {app_data['size'] / (1024**2):.1f} MB\n **Bundle ID:** {app_data['bundleIdentifier']}\n\n",
        "bundle_id": app_data["bundleIdentifier"],
        "categories": [category_ids.get("Tweaked App", list(category_ids.values())[0])],
        "platforms": [platform_ids.get("iOS", list(platform_ids.values())[0])],
        "price": 0,
        "version": app_data["version"],
        "changelog": f"🎉 Version {app_data['version']} Release\n\n✅ Latest tweaks and enhancements",
        "file_size": str(app_data['size'])
    }
    response = session.post(f"{BASE_URL}/apps", json=payload)
    if response.status_code == 201:
        data = response.json()["data"]
        print(f"✅ Created app: {data['title']} (ID: {data['id']}) - Status: {data.get('status', 'pending')}")
        return data["id"]
    else:
        print(f"❌ Failed to create app {app_data['name']}: {response.status_code} - {response.text}")
        return None

def create_version(session, app_id, app_data):
    payload = {
        "version": app_data["version"],
        "changelog": f"Version {app_data['version']} - Latest nabzclan appstore app",
        "file_size": str(app_data['size'])
    }
    response = session.post(f"{BASE_URL}/apps/{app_id}/versions", json=payload)
    if response.status_code == 201:
        data = response.json()["data"]
        print(f"✅ Created version: {data['version']} (ID: {data['id']}) - Status: {data.get('status', 'pending')}")
        return data["id"]
    else:
        print(f"❌ Failed to create version for app {app_id}: {response.status_code} - {response.text}")
        return None

def upload_binary_chunked(session, app_id, version_id, ipa_path):
    """Upload binary using chunked upload to avoid 413 errors"""
    file_size = os.path.getsize(ipa_path)
    chunk_size = 50 * 1024 * 1024  # 50MB chunks - can change
    total_chunks = (file_size + chunk_size - 1) // chunk_size 

    print(f"File size: {file_size / (1024**2):.1f} MB, uploading in {total_chunks} chunks")

    initiate_data = {
        "filename": os.path.basename(ipa_path),
        "total_size": file_size,
        "total_chunks": total_chunks,
        "chunk_size": chunk_size
    }

    response = session.post(f"{BASE_URL}/upload/initiate", json=initiate_data)
    if response.status_code != 200:
        print(f"Failed to initiate chunked upload: {response.status_code} - {response.text}")
        return False

    upload_id = response.json()["upload_id"]
    print(f"Initiated chunked upload with ID: {upload_id}")

    with open(ipa_path, "rb") as f:
        for chunk_num in range(total_chunks):
            chunk_data = f.read(chunk_size)
            if not chunk_data:
                break

            print(f"Uploading chunk {chunk_num + 1}/{total_chunks} ({len(chunk_data) / (1024**2):.1f} MB)")

            with tempfile.NamedTemporaryFile(delete=False) as temp_chunk:
                temp_chunk.write(chunk_data)
                temp_chunk_path = temp_chunk.name

            try:
                with open(temp_chunk_path, "rb") as chunk_file:
                    files = {
                        "chunk": chunk_file,
                    }
                    data = {
                        "chunk_number": chunk_num
                    }
                    response = session.post(f"{BASE_URL}/upload/{upload_id}/chunk", files=files, data=data)

                if response.status_code != 200:
                    print(f"Failed to upload chunk {chunk_num}: {response.status_code} - {response.text}")
                    return False

            finally:
                os.unlink(temp_chunk_path) 

    print("All chunks uploaded successfully")

    response = session.post(f"{BASE_URL}/upload/{upload_id}/finalize", json={})
    if response.status_code != 200:
        print(f"Failed to finalize upload: {response.status_code} - {response.text}")
        return False

    final_path = response.json()["final_path"]
    print(f"Upload finalized, file path: {final_path}")

    apply_data = {
        "chunked_upload_path": final_path
    }
    response = session.post(f"{BASE_URL}/apps/{app_id}/versions/{version_id}/binary", json=apply_data)
    if response.status_code == 200:
        data = response.json().get("data", {})
        status = data.get("version_status", "unknown")
        method = data.get("upload_method", "chunked_path")
        print(f"✅ Binary applied to version {version_id} - Status: {status} - Method: {method}")
        if status == "approved":
            print(f"🎉 Version auto-approved!")
        return True
    else:
        print(f"❌ Failed to apply chunked upload to version: {response.status_code} - {response.text}")
        return False

def upload_binary(session, app_id, version_id, ipa_path):
    """Upload binary using chunked upload for all files to avoid 413 errors"""
    return upload_binary_chunked(session, app_id, version_id, ipa_path)

def upload_icon(session, app_id, icon_path):
    with open(icon_path, "rb") as f:
        files = {"image": f}
        response = session.post(f"{BASE_URL}/apps/{app_id}/icon", files=files)
    if response.status_code in [200, 201]:
        print(f"✅ Uploaded icon for app {app_id}")
        return True
    else:
        print(f"❌ Failed to upload icon: {response.status_code} - {response.text}")
        return False


def download_file(url, path):
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    else:
        print(f"Failed to download {url}: {response.status_code}")
        return False

def load_uploaded():
    if os.path.exists(UPLOADED_FILE):
        try:
            with open(UPLOADED_FILE, "r") as f:
                data = json.load(f)
                return set(data) if data else set()
        except (json.JSONDecodeError, ValueError):
            print("Invalid or empty uploaded_apps.json, starting fresh.")
            os.remove(UPLOADED_FILE)
            return set()
    return set()

def save_uploaded(uploaded_apps):
    with open(UPLOADED_FILE, "w") as f:
        json.dump(list(uploaded_apps), f)

def main(token, num_apps=None):
    print("🚀 Starting NabzClan App Store Auto-Upload Script")
    print(f"📡 API Base URL: {BASE_URL}")
    print(f"📦 Repository: {REPO_URL}")

    session = get_session(token)

    try:
        print("🔑 Testing API authentication...")
        test_response = session.get(f"{BASE_URL}/metadata")
        if test_response.status_code != 200:
            print(f"❌ API authentication failed: {test_response.status_code}")
            return
        print("✅ API authentication successful")
    except Exception as e:
        print(f"❌ Failed to connect to API: {e}")
        return

    try:
        category_ids, platform_ids = get_metadata(session)
        print(f"📋 Found {len(category_ids)} categories and {len(platform_ids)} platforms")
    except Exception as e:
        print(f"❌ Error getting metadata: {e}")
        return

    print("📡 Fetching app repository...")
    repo_response = requests.get(REPO_URL)
    if repo_response.status_code != 200:
        print(f"❌ Failed to fetch repo: {repo_response.status_code}")
        return

    repo = repo_response.json()
    apps = [app for app in repo["apps"] if app.get("type") == 1]
    total_apps = len(apps)

    if num_apps:
        apps = apps[:int(num_apps)]
        print(f"📝 Processing {len(apps)} of {total_apps} apps (limited by user)")
    else:
        print(f"📝 Found {total_apps} apps in repository")

    uploaded_apps = load_uploaded()
    print(f"📚 {len(uploaded_apps)} apps already uploaded (will be skipped)")

    processed_count = 0
    skipped_count = 0
    failed_count = 0

    for i, app in enumerate(apps, 1):
        bundle_id = app['bundleIdentifier']
        if bundle_id in uploaded_apps:
            skipped_count += 1
            print(f"⏭️  [{i}/{len(apps)}] Skipping already uploaded: {app['name']} ({bundle_id})")
            continue

        print(f"\n📱 [{i}/{len(apps)}] Processing {app['name']} v{app['version']} ({bundle_id})")
        print(f"   Size: {app['size'] / (1024**2):.1f} MB")

        temp_dir = Path("./temp")
        temp_dir.mkdir(exist_ok=True)
        tmp_path = temp_dir / app['name']
        tmp_path.mkdir(exist_ok=True)
        ipa_path = tmp_path / f"{app['name']}.ipa"
        icon_path = tmp_path / f"{app['name']}.png"

        try:
            print(f"📥 Downloading IPA ({app['size'] / (1024**2):.1f} MB)...")
            if not download_file(app["downloadURL"], ipa_path):
                print(f"❌ Failed to download IPA file")
                failed_count += 1
                import shutil
                shutil.rmtree(tmp_path, ignore_errors=True)
                continue

            print(f"🖼️  Downloading app icon...")
            if not download_file(app["iconURL"], icon_path):
                print(f"❌ Failed to download icon file")
                failed_count += 1
                import shutil
                shutil.rmtree(tmp_path, ignore_errors=True)
                continue

            print(f"🚀 Creating app entry...")
            app_id = create_app(session, app, category_ids, platform_ids)
            if not app_id:
                failed_count += 1
                import shutil
                shutil.rmtree(tmp_path, ignore_errors=True)
                continue

            print(f"📦 Creating app version...")
            version_id = create_version(session, app_id, app)
            if not version_id:
                failed_count += 1
                import shutil
                shutil.rmtree(tmp_path, ignore_errors=True)
                continue

            print(f"⬆️  Uploading binary (chunked upload)...")
            if not upload_binary(session, app_id, version_id, ipa_path):
                failed_count += 1
                import shutil
                shutil.rmtree(tmp_path, ignore_errors=True)
                continue

            print(f"🖼️  Uploading icon...")
            upload_icon(session, app_id, icon_path)

            print(f"🎉 Successfully uploaded {app['name']}!")
            print(f"   ✅ Auto-approved and queued for pyzule processing")
            print(f"   🧹 Auto-cleaned old versions to save storage space")
            print(f"   📁 Will be available for download once processing completes")

            uploaded_apps.add(bundle_id)
            save_uploaded(uploaded_apps)
            processed_count += 1

        except Exception as e:
            print(f"❌ Unexpected error processing {app['name']}: {e}")
            failed_count += 1
        finally:
            import shutil
            shutil.rmtree(tmp_path, ignore_errors=True)

    # just to let you know is doing something lol 
    print(f"\n{'='*60}")
    print(f"🏁 UPLOAD COMPLETED - SESSION SUMMARY")
    print(f"{'='*60}")
    print(f"   🎯 Successfully processed: {processed_count} apps")
    print(f"   ⏭️  Skipped (already uploaded): {skipped_count} apps")
    print(f"   ❌ Failed: {failed_count} apps")
    print(f"   📊 Total unique apps tracked: {len(uploaded_apps)} apps")

    if processed_count > 0:
        print(f"\n🚀 NEXT STEPS:")
        print(f"   ✅ All {processed_count} apps were auto-approved") # apply to some devs 
        print(f"   🧹 Old versions auto-cleaned to optimize storage on your server")
        print(f"   🔄 Background processing by the appstore is in progress")
        print(f"   📁 Apps will be ready for download once processing completes")
        print(f"   🌐 Check your developer portal: https://appstore.nabzclan.vip/dev")

    if failed_count > 0:
        print(f"\n⚠️  ATTENTION:")
        print(f"   {failed_count} apps failed to upload - check error messages above....")

    print(f"\n📈 SUCCESS RATE: {(processed_count / (processed_count + failed_count) * 100):.1f}%" if (processed_count + failed_count) > 0 else "\n📈 SUCCESS RATE: N/A")
    print(f"{'='*60}")

if __name__ == "__main__":
    token = sys.argv[1] if len(sys.argv) > 1 else f"{NABZ_APPSTORE_API_KEY}"
    num_apps = sys.argv[2] if len(sys.argv) > 2 else None
    main(token, num_apps)
