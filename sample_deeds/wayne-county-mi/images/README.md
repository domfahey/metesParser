# Property Document Images Directory

This directory contains scanned images of property-related documents from Wayne County, Ohio. All images are in TIF (Tagged Image File Format) format, which preserves high quality for document archival and OCR processing.

## Directory Contents

- **Total Images**: 516 TIF files containing 1,301 pages
- **File Format**: TIF (Tagged Image File Format)
- **Page Distribution**: 
  - Single-page files: 347 (69.4%)
  - Multi-page files: 153 (30.6%)
  - Page range: 1-22 pages per file
  - Average pages in multi-page files: 6.2
- **Resolution**: High-resolution scans suitable for OCR and document analysis
- **Source**: Property Insight

## File Naming Convention

All files follow a consistent naming pattern:

```
MIWAYN-[BOOK]-[PAGE].TIF
```

Where:
- `MIWAYN`: State (MI) and County (WAYN) identifier for Michigan, Wayne County
- `[BOOK]`: 5-digit book number (e.g., 50004)
- `[PAGE]`: 5-digit page number (e.g., 01415)

### Example Filenames
- `MIWAYN-50004-01415.TIF` - Book 50004, Page 1415
- `MIWAYN-50005-01119.TIF` - Book 50005, Page 1119
- `MIWAYN-51001-00001.TIF` - Book 51001, Page 1

## Document Types Represented

The images contain various types of property-related documents including:

1. **Property Transfer Documents**
   - Quit Claim Deeds
   - Warranty Deeds
   - Sheriff's Deeds
   - Fiduciary Deeds
   - Special Warranty Deeds

2. **Mortgage Documents**
   - Mortgages
   - Discharge of Mortgages
   - Assignment of Mortgages
   - Satisfaction of Mortgages
   - Mortgage Modifications
   - Subordination Agreements

3. **Tax and Lien Documents**
   - Tax Liens
   - Federal Tax Liens
   - State Tax Liens
   - Lien Releases
   - Certificates of Discharge

4. **Foreclosure Documents**
   - Certificates of Forfeiture
   - Judgments of Foreclosure
   - Redemption Certificates
   - Sheriff's Deeds on Mortgage Sale

5. **Other Legal Documents**
   - Powers of Attorney
   - Certificates of Trust
   - UCC Financing Statements
   - Memorandums of Lease
   - Notices of Commencement

## Image Characteristics

- **Color Depth**: Black and white or grayscale
- **Text Orientation**: Most documents are properly oriented for reading
- **Quality**: Scanned at high resolution to ensure text legibility
- **Document Age**: Recording dates primarily from 2011-2013

## Usage Guidelines

1. **OCR Processing**: These images are suitable for Optical Character Recognition (OCR) to extract text
2. **Machine Learning**: Can be used as training data for document classification and information extraction models
3. **Archival Reference**: Serves as digital archive of original property documents
4. **Ground Truth Validation**: Each image has a corresponding JSON file in the `gt/` folder with extracted data

## Corresponding Ground Truth Data

For each image file, there is a corresponding JSON file in the `../gt/` directory with the same base filename plus `.json` extension:

- Image: `MIWAYN-50004-01415.TIF`
- Ground Truth: `../gt/MIWAYN-50004-01415.TIF.json`

## File Organization

Files are organized alphabetically by book and page number, making it easy to locate specific documents:
- Books range from 50004 to 51001
- Pages vary within each book

## Technical Notes

1. **File Size**: TIF files are uncompressed and may be large
2. **Multi-page Support**: Many files contain multiple pages - ensure your processing tools support multi-page TIFs
3. **Viewing**: Can be viewed with any image viewer that supports multi-page TIF format
4. **Processing**: When using OCR or image processing libraries, ensure they handle multi-page TIFs correctly
5. **Storage**: Consider compression for long-term storage if needed

## Notable Multi-Page Documents

Some files contain significantly more pages than others:
- MIWAYN-50146-01291.TIF: 22 pages
- MIWAYN-50066-00574.TIF: 21 pages
- MIWAYN-50787-01414.TIF: 20 pages
- MIWAYN-50489-01172.TIF: 19 pages
- MIWAYN-50808-01116.TIF: 19 pages

These typically represent more complex transactions or documents with multiple exhibits.

## Missing Images

Some book/page combinations may be missing if:
- The original document was not available for scanning
- The page was blank or contained non-relevant content
- Technical issues prevented successful scanning

## Data Source

These images are sourced from Wayne County public records. All information contained within these documents is part of the public record as filed with the Wayne County Recorder's Office. The documents contain:
- Personal names and addresses
- Property descriptions  
- Financial information (sale amounts, loan amounts)
- Legal descriptions

This information was already publicly available when recorded with the county.