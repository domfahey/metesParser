# Ground Truth Data Directory

This directory contains structured JSON files with extracted data from the corresponding property document images. Each JSON file represents the ground truth data manually extracted or verified from the scanned documents.

## Directory Contents

- **Total JSON Files**: 492 files
- **File Format**: JSON (JavaScript Object Notation)
- **Additional Files**: 2 Excel spreadsheets with ground truth data in different formats
- **Source**: Data extracted by Property Insight

## File Naming Convention

JSON files follow the pattern:

```
MIWAYN-[BOOK]-[PAGE].TIF.json
```

This matches the corresponding image filename with `.json` appended:
- Image: `../images/MIWAYN-50004-01415.TIF`
- JSON: `MIWAYN-50004-01415.TIF.json`

## JSON Schema Structure

Each JSON file contains a consistent hierarchical structure with the following main sections:

### 1. Header Section
Contains document metadata and recording information:

```json
{
  "Header": {
    "Recording_State": "Michigan",
    "Recording_County": "Wayne",
    "Recording_Book_Number": "50004",
    "Recording_Page_Number": "1415",
    "Recording_File_Number": "2012309997",
    "Recording_Date_And_Time": "25-July-2012",
    "Title_Company_Name": "NA",
    "Document_Title": "QUIT CLAIM DEED",
    "Document_Type": "Quit Claim Deed",
    "Dated_Date": "18-June-2012",
    "Sale_Amount": "$1.00",
    "Loan_Details": { ... },
    "Type_Of_Financing": "NA",
    "Case_Number": "NA",
    "Case_Type": "NA",
    "Judgement_Details": [ ... ],
    "Lien_Details": [ ... ],
    "MERS_MIN_Number": "NA",
    "MERS_Phone_Number": "NA",
    "Tax_Details": [ ... ]
  }
}
```

### 2. Parties Section
Lists all parties involved in the document:

```json
{
  "Parties": [
    {
      "Name": "John Doe",
      "Relationship_Status": "Single",
      "Role": "Grantor",
      "Mailing_Address": "123 Main St, Detroit, MI 48201",
      "Social_Security_Number": "NA"
    }
  ]
}
```

**Common Roles**:
- Grantor/Grantee (property transfers)
- Borrower/Lender (mortgages)
- Mortgagor/Mortgagee
- Assignor/Assignee
- Taxpayer
- Trustee
- Attorney

### 3. Vesting Section
Describes how title is held:

```json
{
  "Vesting": {
    "Buyer_Or_Borrower_Vesting_Details": [
      {
        "Vesting_Details": "John Doe, a single man"
      }
    ],
    "Seller_Or_Lender_Vesting_Details": [
      {
        "Vesting_Details": "Jane Smith, a married woman"
      }
    ]
  }
}
```

### 4. Properties Section
Contains property information:

```json
{
  "Properties": [
    {
      "Property_Type": "Residential",
      "Property_Address": "123 Main St, Detroit, MI 48201",
      "Assessors_Parcel_Numbers_Or_Parcel_Ids": [
        {
          "APN": "12-345-678-910"
        }
      ],
      "Property_Owners": [ ... ]
    }
  ]
}
```

### 5. Legal Description Sections

**Full Legal Description**: Complete text of the legal description
```json
{
  "Full_Legal_Description": "LOT 63, MACK-GROSSE POINTE SUBDIVISION..."
}
```

**Parsed Legal Description**: Structured breakdown of legal description components
```json
{
  "Legal_Descriptions": [
    {
      "Legal_Description": "...",
      "Legal_Description_Attributes": {
        "Unit": "NA",
        "Lot": "63",
        "Block": "NA",
        "Building": "NA",
        "Phase": "NA",
        "Plat_Number": "NA",
        "Map_Name": "MACK-GROSSE POINTE",
        "Map_Book_Or_Condo_Book": "51",
        "Map_Page_Or_Condo_Page": "22",
        "City": "Grosse Pointe Farms",
        "Sub_Division": "MACK-GROSSE POINTE",
        ...
      }
    }
  ]
}
```

### 6. Prior Document References
Links to related documents:

```json
{
  "Primary_Or_Prior_Document_Details": [
    {
      "Primary_Or_Prior_Document_Name": "Warranty Deed",
      "Primary_Or_Prior_Document_Date": "15-May-2010",
      "Primary_Or_Prior_Document_Number": "2010123456",
      "Primary_Or_Prior_Book_Number": "48950",
      "Primary_Or_Prior_Page_Number": "125"
    }
  ]
}
```

## Data Standards

### NA Values
Fields that are not applicable or not available are marked as "NA". This includes:
- Information not present in the document
- Fields not relevant to the document type
- Redacted or illegible information

### Date Formats
Dates typically follow the pattern: `DD-Month-YYYY`
- Example: "25-July-2012"
- Some variations may exist

### Monetary Values
- Include dollar sign: `"$100,000.00"`
- May include cents: `"$1.00"`
- NA when not applicable

### Custom Fields
Some entries include `"isATCustom": "True"` indicating special processing or custom data entry.

## Additional Files

### Excel Spreadsheets
1. **`Ground Truth_As is.xlsx`** - Original ground truth data format
2. **`Ground Truth_ERL_ Format.xlsx`** - Ground truth in ERL (Entity-Relationship-Label) format

These spreadsheets may contain:
- Batch processing information
- Alternative data formats
- Quality control annotations
- Processing metadata

## Data Quality Notes

1. **Completeness**: Not all fields are populated for every document type
2. **Consistency**: While the schema is consistent, field usage varies by document type
3. **Accuracy**: Data has been extracted/verified but may contain human transcription errors
4. **Coverage**: 492 JSON files for 516 images (some images may not have corresponding JSON)

## Usage Examples

### Loading a JSON file (Python):
```python
import json

with open('MIWAYN-50004-01415.TIF.json', 'r') as f:
    data = json.load(f)
    
# Access document type
doc_type = data['Header']['Document_Type']

# Get all party names
parties = [p['Name'] for p in data['Parties']]

# Extract property address
property_addr = data['Properties'][0]['Property_Address']
```

### Finding specific document types:
```python
import glob
import json

quit_claims = []
for filename in glob.glob('*.json'):
    with open(filename, 'r') as f:
        data = json.load(f)
        if data['Header']['Document_Type'] == 'Quit Claim Deed':
            quit_claims.append(filename)
```

## Field Statistics

Based on analysis of all JSON files:
- **Total unique fields**: 385
- **High completion fields** (>80%): Core header fields, party names, document types
- **Low completion fields** (<20%): Specialized fields like loan terms, judgment details
- **Most common document types**: Certificate of Forfeiture (20%), Quit Claim Deed (10%)

## Notes for Researchers

1. This ground truth data can be used for:
   - Training document understanding models
   - Evaluating OCR accuracy
   - Developing information extraction systems
   - Real estate market analysis

2. Consider the temporal aspect - most documents are from 2011-2013

3. The hierarchical JSON structure reflects the complex nature of legal documents

4. Some fields may have inconsistent formatting due to manual data entry

## Data Source Note

This ground truth data is derived from Wayne County public records. All information was extracted from documents that are part of the public record as filed with the Wayne County Recorder's Office, including:
- Personal names and addresses
- Financial information
- Legal descriptions of properties

This dataset represents internal work product based on publicly available information.