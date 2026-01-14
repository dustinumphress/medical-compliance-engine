# medical-compliance-engine

A comprehensive, AI-powered medical coding audit system designed to verify CPT codes against clinical documentation, enforce NCCI/MUE billing rules, and ensure compliance.

## 🚀 Key Features

*   **AI-Powered Verification**: Uses Anthropic's Claude 3.5 Sonnet to analyze sanitized clinical text and verify if documentation supports billed CPT codes.
*   **Regulatory Compliance Engine**:
    *   **NCCI Checks**: Deterministic checks for National Correct Coding Initiative (NCCI) bundling edits (PTP).
    *   **MUE Checks**: Enforces Medically Unlikely Edits (MUE) limits based on user-provided units.
    *   **Hybrid Lookup**: Prioritizes custom "Augmented Rules" for specific payer requirements, falling back to an official CPT database (ingested from RVU files) for standard definitions.
*   **Privacy First**:
    *   **Local PHI Redaction**: Microsoft Presidio runs LOCALLY to redact Patient Names, MRNs, Dates, and other identifiers *before* data leaves your machine.
    *   **Redaction Viewer**: Review and approve sanitized text in the UI before submission.
*   **Interactive Web UI**: Clean, dark-mode Flask application for easy data entry (Calculated vs. Billed Units display).
*   **Production Ready**: Includes `Dockerfile` for easy deployment, comprehensive logging, and automated test suite.

## 🛠️ Architecture

The project follows a **3-Layer Architecture** (Directive, Orchestration, Execution):

*   **`app.py`** (Orchestration): The Flask web server acting as the entry point and controller.
*   **`execution/`** (Execution): Deterministic Python scripts handling the logic.
    *   `medical_audit.py`: Main audit logic, LLM integration, and rule merging.
    *   `sanitize_phi.py`: Presidio configuration for PHI redaction.
    *   `ingest_coding_rules.py`: ETL script to populate the SQLite database.
    *   `cpt_data.py`: Custom/Augmented CPT rule definitions.
*   **`coding_rules.db`**: SQLite database storing NCCI edits, MUE limits, and Official CPT descriptions.

## ☁️ Cloud Architecture Roadmap (AWS)

This project is designed to be deployed as a Serverless Microservice on AWS.

*   **Compute**: Dockerized Lambda function (Eer) running the `medical_audit.py` logic.
*   **Orchestration**: API Gateway to handle RESTful audit requests.
*   **Security**:
    *   `ANTHROPIC_API_KEY` stored in **AWS Secrets Manager**.
    *   **AWS WAF** (Web Application Firewall) to rate-limit requests.
*   **Privacy**: Presidio redaction runs within the Lambda execution environment (ephemeral), ensuring PHI is never persisted to disk.
*   **CI/CD**: GitHub Actions pipeline to build the Docker image and push to Amazon ECR (Elastic Container Registry) on merge.

## 📦 Setup & Installation

1.  **Prerequisites**: Python 3.12+, SQLite3.
2.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    python -m spacy download en_core_web_lg
    ```
3.  **Environment Variables**:
    Create a `.env` file in the root directory:
    ```env
    ANTHROPIC_API_KEY=sk-ant-...
    ```

## 📥 Data Initialization (ETL Pipeline)

This application relies on the official CMS Physician Fee Schedule, NCCI Bundling Edits, and MUE Limits. Due to data size and frequency of updates, these files are not committed to the repository.

You must download the raw public use files from CMS.gov and run the ingestion script to build the local SQLite database (`coding_rules.db`).

### 1. Download Required Files
Create a folder named `inputs/` in the root directory and place the following three files inside.

| Data Type | Source & Download Instructions | Required Filename (Rename if needed) |
| :--- | :--- | :--- |
| **RVU (Definitions)** | [CMS Physician Fee Schedule](https://www.cms.gov/medicare/payment/fee-schedules/physician-fee-schedule/pfs-relative-value-files) <br> Download the "2026 National Physician Fee Schedule Relative Value File". Use the `.txt` version inside the zip. | `PPRRVU2026_Jan_nonQPP.txt` |
| **NCCI (Bundling)** | [CMS PTP Coding Edits](https://www.cms.gov/medicare/coding-billing/ncci-medicare/practitioner-ptp-edits) <br> Select "Practitioner PTP Edits". Download the Text Format (English) version. | `ccipra-2026.txt` |
| **MUE (Limits)** | [CMS MUE Tables](https://www.cms.gov/medicare/coding-billing/ncci-medicare/medicare-ncci-procedure-to-procedure-ptp-edits/practitioner-ptp-edits) <br> Select "Practitioner Services MUE Table". Download the CSV version. | `MCR_MUE_Practitioner.csv` |

### 2. Expected Directory Structure
Ensure your folder looks like this before running the script:

```
├── execution/
│   └── ingest_coding_rules.py
├── inputs/
│   ├── PPRRVU2026_Jan_nonQPP.txt
│   ├── ccipra-2026.txt
│   └── MCR_MUE_Practitioner.csv
└── app.py
```

### 3. Run the Ingestion Script
This script parses the raw text/CSV data and populates the `coding_rules.db` SQLite database.

```bash
python execution/ingest_coding_rules.py
```

**Success Output:**
```text
[INFO] Database initialized at coding_rules.db
[SUCCESS] Imported 14201 MUE records.
[SUCCESS] Imported 68204 NCCI edits.
[SUCCESS] Inserted 8500 CPT descriptions.
[DONE] Database rebuild complete.
```

5.  **Docker Setup (Optional)**:
    Build the container image:
    ```bash
    docker build -t medical-audit .
    ```

## 🖥️ Usage

1.  **Start the Web Application**:
    ```bash
    python app.py
    ```
    **OR** via Docker:
    ```bash
    docker run --env-file .env -p 5000:5000 medical-audit
    ```
2.  **Access the Dashboard**:
    Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.
3.  **Perform an Audit**:
    *   Paste the **Operative Report** or Clinical Note.
    *   Enter **CPT Codes** and **Units**.
    *   Click **"Review Redaction"** to see what the AI will see.
    *   Click **"Run Audit"** to get results.

## 📊 Logic Flow

1.  **Sanitization**: Input text -> `sanitize_phi.py` -> `<REDACTED>` text.
2.  **Rule Check**: CPTs -> `coding_rules.db` -> NCCI/MUE Alerts (High Risk).
3.  **AI Analysis**: Redacted Text + CPT Definitions + Alerts -> LLM -> Clinical Validation.
4.  **Result Merger**: The system merges the Deterministic Rules (Database) with the Probabilistic Clinical Findings (LLM) into a single human-readable rationale.

## 📁 Directory Structure

```
├── app.py                  # Flask Web Server
├── coding_rules.db         # SQLite Database (Rules & Descs)
├── execution/              # Core Logic Scripts
│   ├── medical_audit.py    # Auditor Engine
│   ├── sanitize_phi.py     # Privacy Engine
│   ├── ingest_coding_rules.py # DB Builder
│   └── cpt_data.py         # Custom Rules Module
├── templates/              # HTML Templates
├── static/                 # CSS/JS Assets
├── tests/                  # Automated Tests
└── requirements.txt        # Python Dependencies
```

## 🧪 Testing

The project includes a `pytest` test suite to verify internal logic (especially PHI sanitization) without incurring LLM costs.

1.  **Install Test Dependencies**:
    ```bash
    pip install pytest
    ```
2.  **Run Tests**:
    ```bash
    pytest
    ```

## 🤝 Contributing

Contributions are welcome!
1.  Fork the Project
2.  Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3.  Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4.  Push to the Branch (`git push origin feature/AmazingFeature`)
5.  Open a Pull Request

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.
