# Data Dictionary

This document provides detailed descriptions of all fields in the ground truth JSON files.

## Table of Contents

- [Header Fields](#header-fields)
- [Parties Fields](#parties-fields)
- [Vesting Fields](#vesting-fields)
- [Properties Fields](#properties-fields)
- [Legal Descriptions Fields](#legal-descriptions-fields)
- [Prior Document Fields](#prior-document-fields)

## Header Fields

The Header object contains document metadata and recording information.

| Field Name | Type | Description | Example |
|------------|------|-------------|---------|
| Recording_State | String | State where document was recorded | "Michigan" |
| Recording_County | String | County where document was recorded | "Wayne" |
| Recording_Book_Number | String | Book number in county records | "50004" |
| Recording_Page_Number | String | Page number within the book | "1415" |
| Recording_File_Number | String | Unique file number assigned by recorder | "2012309997" |
| Recording_Date_And_Time | String | Date and time of recording | "25-July-2012" |
| Title_Company_Name | String | Name of title company (if applicable) | "First Title Agency" or "NA" |
| Document_Title | String | Title as appears on document | "QUIT CLAIM DEED" |
| Document_Type | String | Standardized document type | "Quit Claim Deed" |
| Dated_Date | String | Date document was signed/executed | "18-June-2012" |
| Sale_Amount | String | Sale price if applicable | "$100,000.00" or "NA" |
| Type_Of_Financing | String | Type of financing used | "FHA", "Conventional", or "NA" |
| Case_Number | String | Court case number if applicable | "12-CV-12345" or "NA" |
| Case_Type | String | Type of court case | "Foreclosure" or "NA" |
| MERS_MIN_Number | String | MERS Mortgage ID Number | "1234567890" or "NA" |
| MERS_Phone_Number | String | MERS contact phone | "1-888-555-1234" or "NA" |

### Nested Objects in Header

#### Loan_Details

| Field Name | Type | Description |
|------------|------|-------------|
| Loan_Number | String | Lender's loan number |
| Loan_Amount | String | Original loan amount |
| Interest_Rate | String | Interest rate on loan |
| Loan_Term | String | Length of loan term |
| Loan_Term_End_Date | String | Maturity date of loan |
| Loan_Type | String | Type of loan (Fixed, ARM, etc.) |

#### Judgement_Details (Array)

| Field Name | Type | Description |
|------------|------|-------------|
| Judgement_Type | String | Type of judgment |
| Judgement_Entered_Date | String | Date judgment was entered |
| Judgement_Amount_In_Total | String | Total judgment amount |
| Judgement_Amount_Paid | String | Amount paid to date |
| Judgement_Amount_Due | String | Remaining balance due |

#### Lien_Details (Array)

| Field Name | Type | Description |
|------------|------|-------------|
| Lien_Type | String | Type of lien (Tax, Mechanic's, etc.) |
| Lien_Entered_Date | String | Date lien was filed |
| Lien_Amount_In_Total | String | Total lien amount |
| Lien_Amount_Paid | String | Amount paid |
| Lien_Amount_Due | String | Balance due |
| Lien_Claimant_Details | Array | Details about lien claimants |

#### Tax_Details (Array)

| Field Name | Type | Description |
|------------|------|-------------|
| Tax_Amount | String | Tax amount owed |
| Tax_Payer_Name | String | Name of taxpayer |
| Tax_Type | String | Type of tax |

## Parties Fields

Array of party objects involved in the transaction.

| Field Name | Type | Description | Example |
|------------|------|-------------|---------|
| Name | String | Full name of party | "John David Smith" |
| Relationship_Status | String | Marital/relationship status | "Single", "Married", "Wife", "Husband" |
| Role | String | Role in transaction | "Grantor", "Grantee", "Borrower", "Lender" |
| Mailing_Address | String | Mailing address | "123 Main St, Detroit, MI 48201" |
| Social_Security_Number | String | SSN (always "NA" for privacy) | "NA" |
| isATCustom | String | Custom processing flag | "True" or undefined |

### Common Roles

- **Grantor**: Person giving/selling property
- **Grantee**: Person receiving/buying property
- **Mortgagor**: Borrower in mortgage
- **Mortgagee**: Lender in mortgage
- **Assignor**: Party assigning rights
- **Assignee**: Party receiving assigned rights
- **Taxpayer**: Property tax payer
- **Trustee**: Trustee in trust deed
- **Beneficiary**: Beneficiary of trust

## Vesting Fields

Describes how title is held.

| Field Name | Type | Description |
|------------|------|-------------|
| Buyer_Or_Borrower_Vesting_Details | Array | How buyer/borrower holds title |
| Seller_Or_Lender_Vesting_Details | Array | How seller/lender held title |

Each array contains objects with:
- `Vesting_Details`: String describing vesting (e.g., "John Doe, a single man")

## Properties Fields

Array of property objects.

| Field Name | Type | Description | Example |
|------------|------|-------------|---------|
| Property_Type | String | Type of property | "Residential", "Commercial" |
| Property_Address | String | Full property address | "123 Main St, Detroit, MI 48201" |
| Assessors_Parcel_Numbers_Or_Parcel_Ids | Array | APN information | |
| Property_Owners | Array | Current owners | |

### APN Object

| Field Name | Type | Description |
|------------|------|-------------|
| APN | String | Assessor's Parcel Number |

## Legal Descriptions Fields

| Field Name | Type | Description |
|------------|------|-------------|
| Full_Legal_Description | String | Complete legal description text |
| Legal_Descriptions | Array | Parsed legal descriptions |

### Legal_Description_Attributes

Detailed parsing of legal description components:

| Field Name | Type | Description | Example |
|------------|------|-------------|---------|
| Unit | String | Unit number | "12A" or "NA" |
| Lot | String | Lot number | "63" |
| Block | String | Block number | "5" or "NA" |
| Building | String | Building identifier | "Building A" or "NA" |
| Phase | String | Development phase | "Phase 2" or "NA" |
| Plat_Number | String | Plat number | "12345" or "NA" |
| Map_Name | String | Subdivision/map name | "MACK-GROSSE POINTE" |
| Map_Book_Or_Condo_Book | String | Plat book number | "51" |
| Map_Page_Or_Condo_Page | String | Plat page number | "22" |
| City | String | City name | "Detroit" |
| Sub_Division | String | Subdivision name | "MACK-GROSSE POINTE" |
| Section | String | Section number | "12" or "NA" |
| Township | String | Township | "1N" or "NA" |
| Range | String | Range | "12E" or "NA" |

## Prior Document Fields

References to related documents.

| Field Name | Type | Description | Example |
|------------|------|-------------|---------|
| Primary_Or_Prior_Document_Name | String | Type of prior document | "Warranty Deed" |
| Primary_Or_Prior_Document_Date | String | Date of prior document | "15-May-2010" |
| Primary_Or_Prior_Document_Number | String | Recording number | "2010123456" |
| Primary_Or_Prior_Book_Number | String | Book number | "48950" |
| Primary_Or_Prior_Page_Number | String | Page number | "125" |
| isATCustom | String | Custom processing flag | "True" or undefined |

## Special Values

### "NA" Values

The string "NA" is used consistently throughout the dataset to indicate:
- Field not applicable to this document type
- Information not available in the source document
- Information redacted for privacy (e.g., SSN)
- Field left blank in original document

### Date Formats

Dates typically follow the pattern: `DD-Month-YYYY`
- Example: "25-July-2012"
- Some variations may exist

### Monetary Formats

Money values include currency symbol and decimal:
- Example: "$100,000.00"
- Small amounts: "$1.00"
- When not applicable: "NA"

### Custom Fields

Fields with `isATCustom: "True"` indicate special processing or manual intervention was required during data extraction.