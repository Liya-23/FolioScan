# FolioScan

FolioScan is a web-based folder scanning and Excel reporting engine for messy filename data. It recursively scans a folder tree, extracts structured identity and tracking fields from every filename, then writes a clean Excel output into the scanned folder.

## Features

- Tornado web server with API endpoints
- Live dashboard for starting scans and viewing logs
- Background job processing
- Recursive folder scanning
- DOB extraction and normalization
- Tracking ID, email, read receipt, document label, and noise filtering
- File path, size, modified date, created date, and scan date capture
- Clean Excel export

## Project Structure

```text
folioscan_project/
  backend/
    processor.py
    server.py
  frontend/
    app.js
    index.html
    styles.css
  requirements.txt
  README.md
```

## Install

```powershell
cd C:\Users\SAMI\Documents\Codex\2026-06-17\folioscan-system-full-presentation-overview-1\outputs\folioscan_project
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python .\backend\server.py
```

Open:

```text
http://localhost:8888
```

## API

Start a scan:

```http
POST /api/scan
Content-Type: application/json

{
  "folder_path": "C:\\Users\\SAMI\\Documents\\UiPath\\Home Affairs Follow Up folder\\data"
}
```

Check a job:

```http
GET /api/job/{job_id}
```

## Output

The cleaned file is saved inside the scanned folder:

```text
folioscan_output.xlsx
```

Columns:

- `FirstName`
- `SecondName`
- `LastName`
- `DOB`
- `FileExtension`
- `Email Sent`
- `Read Receipts`
- `Email Sent Date`
- `Read Receipt receved date`
- `FilePath`
- `FileSizeKB`
- `DateModified`
- `DateCreated`
- `DateScanned`
- `Notes`
# FolioScan
