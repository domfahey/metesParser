# Wayne County Ohio Property Document Dataset

[![Dataset Size](https://img.shields.io/badge/Size-1.3GB-blue.svg)]()
[![Documents](https://img.shields.io/badge/Documents-516-green.svg)]()
[![Pages](https://img.shields.io/badge/Pages-1301-orange.svg)]()
[![Internal](https://img.shields.io/badge/Access-Internal%20Only-red.svg)]()

An internal corporate dataset of scanned property documents from Wayne County, Ohio, with corresponding ground truth annotations. This dataset contains 516 high-resolution document images sourced from Wayne County public records and structured JSON files with extracted data, suitable for document analysis, OCR training, and property data research.

## Table of Contents

- [Overview](#overview)
- [Dataset Description](#dataset-description)
- [Repository Structure](#repository-structure)
- [Data Format](#data-format)
- [Quick Start](#quick-start)
- [Usage Examples](#usage-examples)
- [Dataset Statistics](#dataset-statistics)
- [Applications](#applications)
- [Requirements](#requirements)
- [Citation](#citation)
- [License](#license)
- [Contributing](#contributing)
- [Acknowledgments](#acknowledgments)

## Overview

This internal dataset was created by Property Insight using public property records sourced from Wayne County, Ohio. It includes various types of property-related documents such as deeds, mortgages, liens, and foreclosure documents, along with manually verified ground truth data extracted from each document. This dataset is for internal corporate use only.

### Key Features

- **516 high-resolution TIF images** containing 1,301 pages total
- **492 ground truth JSON files** with structured data extraction
- **Multiple document types**: Quit Claim Deeds, Mortgages, Tax Liens, Foreclosure Certificates, etc.
- **Recording period**: Primarily 2011-2013
- **Multi-page support**: 30.6% of documents contain multiple pages (2-22 pages)

## Dataset Description

### Document Types Distribution

| Document Type | Count | Percentage |
|--------------|-------|------------|
| Certificate of Forfeiture | 100 | 20.3% |
| Quit Claim Deed | 47 | 9.6% |
| Certificate of Redemption | 43 | 8.7% |
| Mortgage | 43 | 8.7% |
| Discharge of Mortgage | 33 | 6.7% |
| Other Types | 226 | 45.9% |

### Page Distribution

- **Single-page documents**: 347 (69.4%)
- **Multi-page documents**: 153 (30.6%)
- **Page range**: 1-22 pages per document
- **Total pages**: 1,301

## Repository Structure

```
wayne-county-mi/
├── README.md                    # This file
├── CHANGELOG.md                 # Dataset change history
├── DATA_DICTIONARY.md           # Field definitions and data dictionary
├── images/                      # Original scanned documents
│   ├── README.md               # Detailed image documentation
│   └── *.TIF                   # 516 TIF files
├── pdfs/                        # Losslessly converted PDFs
├── gt/                         # Ground truth annotations
│   ├── README.md               # Ground truth schema documentation
│   ├── *.json                  # 492 JSON files
│   ├── Ground Truth_As is.xlsx
│   └── Ground Truth_ERL_Format.xlsx
├── scripts/                     # Analysis and utility scripts
│   ├── analyze_dataset.py      # Dataset analysis
│   ├── audit_dates.py          # Date field auditing
│   ├── check_tif_pages.py      # TIF page count verification
│   ├── create_image_inventory.py # Inventory generation
│   ├── detailed_analysis.py    # Advanced analysis tools
│   ├── normalize_book_page.py  # Book/page normalization
│   ├── normalize_dates.py      # Date normalization
│   └── update_inventory_pages.py # Inventory page updates
└── analysis/                    # Generated analysis outputs
    ├── analysis_report.txt     # Dataset analysis summary
    ├── data_quality_issues.csv # Quality issue report
    ├── field_statistics.csv    # Field-level statistics
    ├── field_value_frequencies.csv # Value frequency analysis
    ├── image_inventory.csv     # Complete metadata for all images
    ├── import_audit.json       # Import audit log
    ├── pdf_gt_mapping.csv      # PDF to GT file mapping
    ├── tif_inventory.csv       # TIF file inventory
    └── *.png                   # Analysis visualizations
```

## Data Format

### Image Files

- **Format**: TIF (Tagged Image File Format)
- **Naming Convention**: `MIWAYN-[BOOK]-[PAGE].TIF`
  - Example: `MIWAYN-50004-01415.TIF` (Book 50004, Page 1415)
- **Resolution**: High-resolution scans suitable for OCR
- **Color**: Black and white or grayscale

### Ground Truth JSON Structure

Each JSON file contains:

```json
{
  "Header": {
    "Recording_State": "Michigan",
    "Recording_County": "Wayne",
    "Recording_Book_Number": "50004",
    "Recording_Page_Number": "1415",
    "Document_Type": "Quit Claim Deed",
    ...
  },
  "Parties": [
    {
      "Name": "John Doe",
      "Role": "Grantor",
      "Relationship_Status": "Single",
      ...
    }
  ],
  "Properties": [...],
  "Legal_Descriptions": [...],
  "Vesting": {...},
  "Primary_Or_Prior_Document_Details": [...]
}
```

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/fnf-corp/wayneohcounty.git
cd wayneohcounty
```

### 2. Explore the Data

```python
import json
import os
from PIL import Image

# Load a sample ground truth file
with open('gt/MIWAYN-50004-01415.TIF.json', 'r') as f:
    data = json.load(f)
    print(f"Document Type: {data['Header']['Document_Type']}")
    print(f"Recording Date: {data['Header']['Recording_Date_And_Time']}")

# Open corresponding image
img = Image.open('images/MIWAYN-50004-01415.TIF')
img.show()
```

### 3. Run Analysis

```bash
python scripts/analyze_dataset.py
```

## Usage Examples

### Finding Specific Document Types

```python
import glob
import json

# Find all Quit Claim Deeds
quit_claims = []
for filename in glob.glob('gt/*.json'):
    with open(filename, 'r') as f:
        data = json.load(f)
        if data['Header']['Document_Type'] == 'Quit Claim Deed':
            quit_claims.append(filename)

print(f"Found {len(quit_claims)} Quit Claim Deeds")
```

### Processing Multi-Page Documents

```python
import pandas as pd

# Load inventory to identify multi-page documents
inventory = pd.read_csv('image_inventory.csv')
multi_page = inventory[inventory['page_count'] > 1]

print(f"Multi-page documents: {len(multi_page)}")
print(f"Max pages in a document: {inventory['page_count'].max()}")
```

### Extracting Property Addresses

```python
import json
import glob

addresses = []
for filename in glob.glob('gt/*.json'):
    with open(filename, 'r') as f:
        data = json.load(f)
        for prop in data.get('Properties', []):
            if prop.get('Property_Address') != 'NA':
                addresses.append(prop['Property_Address'])

print(f"Found {len(addresses)} property addresses")
```

## Dataset Statistics

### Summary Statistics

- **Total Documents**: 516 (492 with ground truth)
- **Total Pages**: 1,301
- **Average File Size**: 0.14 MB
- **Total Dataset Size**: ~70 MB (images only)
- **Date Range**: 2011-2013
- **Geographic Coverage**: Wayne County, Ohio (primarily Detroit area)

### Data Quality

- **Ground Truth Coverage**: 95.3% (492/516 documents)
- **Field Completion Rate**: Core fields >80%, specialized fields <20%
- **Common NA Fields**: SSN, loan details, judgment amounts

### Top Property Locations

1. Detroit - 127 properties
2. Canton - 15 properties
3. Dearborn - 14 properties
4. Wayne - 14 properties
5. Livonia - 7 properties

## Applications

This dataset is suitable for:

1. **Document Analysis & OCR**
   - Training OCR models for legal documents
   - Document layout analysis
   - Multi-page document processing

2. **Information Extraction**
   - Named entity recognition (parties, addresses)
   - Legal description parsing
   - Relationship extraction

3. **Real Estate Research**
   - Property transaction analysis
   - Market trend studies
   - Foreclosure pattern analysis

4. **Machine Learning**
   - Document classification
   - Data extraction models
   - Ground truth validation

## Requirements

### Software Dependencies

- Python 3.7+
- Required packages:
  ```bash
  pip install pillow pandas numpy
  ```

### Hardware Requirements

- **Storage**: ~1.5 GB for complete dataset
- **RAM**: 4 GB minimum for processing
- **Processing**: Multi-page TIF support required

## Data Usage and Access

This is an **internal corporate dataset** for use within the organization only. 

### Data Sources
- **Images**: Sourced from Wayne County, Ohio public records
- **Annotations**: Created internally by Property Insight

### Important Notes
- This dataset is not licensed for external distribution
- The original documents are public records but this compilation is proprietary
- For internal use only - do not share outside the organization
- All information contained within is already part of the public record as recorded with Wayne County
- No warranty is provided for data accuracy or completeness

## Contributing

For internal team members who wish to contribute improvements:

1. **Report Issues**: File issues for data quality problems
2. **Enhance Documentation**: Submit PRs for documentation improvements
3. **Add Analysis Tools**: Contribute analysis scripts or notebooks
4. **Improve Ground Truth**: Report errors in JSON annotations

### Internal Contribution Guidelines

1. Create a feature branch (`git checkout -b feature/improvement`)
2. Commit your changes (`git commit -am 'Add new feature'`)
3. Push to the branch (`git push origin feature/improvement`)
4. Create a Pull Request for team review

## Acknowledgments

- **Property Insight**: For sourcing and providing the dataset
- **Wayne County, Ohio**: For maintaining public records
- **Contributors**: All who help improve this dataset

---

For questions or support, please open an issue on GitHub or contact the maintainers.