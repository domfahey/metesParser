# Changelog

All notable changes to this dataset will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2024-01-31

### Added
- Comprehensive README with best practices structure
- Detailed documentation for `images/` and `gt/` directories
- Complete image inventory CSV with metadata:
  - SHA-256 hashes for all files
  - Accurate page counts (discovered 153 multi-page TIFs)
  - File sizes and modification dates
- Python analysis scripts:
  - `analyze_dataset.py` - Basic dataset analysis
  - `detailed_analysis.py` - Advanced analysis with visualizations
  - `create_image_inventory.py` - Inventory generation
  - `update_inventory_pages.py` - Page count verification
- Dataset statistics and visualizations
- Usage examples and code snippets
- Citation information

### Changed
- Updated documentation to reflect multi-page documents (30.6% of dataset)
- Corrected total page count from 516 to 1,301 pages
- Enhanced README with table of contents, badges, and structured sections

### Fixed
- Incorrect assumption that all TIF files were single-page documents

## [1.0.0] - 2024-01-31

### Added
- Initial dataset release
- 516 TIF document images from Wayne County, Ohio
- 492 ground truth JSON files with extracted data
- 2 Excel files with ground truth in different formats
- Basic README documentation

---

*Note: Dates reflect when changes were made to the repository, not the original document recording dates (2011-2013)*