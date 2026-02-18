import json
import os
import re
from collections import Counter
from datetime import datetime


def load_json_files(directory):
    """Load all JSON files from the gt directory"""
    json_data = []
    for filename in os.listdir(directory):
        if filename.endswith('.json'):
            filepath = os.path.join(directory, filename)
            with open(filepath) as f:
                data = json.load(f)
                data['_filename'] = filename
                json_data.append(data)
    return json_data

def parse_date(date_str):
    """Parse various date formats"""
    if date_str == "NA" or not date_str:
        return None

    # Remove extra spaces
    date_str = date_str.strip()

    # Try different date formats
    formats = [
        "%d-%B-%Y",
        "%d-%b-%Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%Y-%m-%d"
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    return None

def parse_amount(amount_str):
    """Parse monetary amounts"""
    if amount_str == "NA" or not amount_str:
        return None

    # Remove $ and commas
    amount_str = amount_str.replace('$', '').replace(',', '').strip()

    try:
        return float(amount_str)
    except ValueError:
        return None

def analyze_documents(json_data):
    """Perform comprehensive analysis of the documents"""

    analysis = {
        'total_documents': len(json_data),
        'document_types': Counter(),
        'recording_years': Counter(),
        'recording_months': Counter(),
        'party_roles': Counter(),
        'party_relationships': Counter(),
        'property_types': Counter(),
        'cities': Counter(),
        'subdivisions': Counter(),
        'sale_amounts': [],
        'loan_amounts': [],
        'has_loan_info': 0,
        'has_lien_info': 0,
        'has_judgment_info': 0,
        'has_tax_info': 0,
        'has_prior_docs': 0,
        'apn_patterns': Counter(),
        'title_companies': Counter(),
        'financing_types': Counter()
    }

    for doc in json_data:
        header = doc.get('Header', {})

        # Document types
        doc_type = header.get('Document_Type', 'Unknown')
        analysis['document_types'][doc_type] += 1

        # Recording dates
        rec_date = parse_date(header.get('Recording_Date_And_Time', 'NA'))
        if rec_date:
            analysis['recording_years'][rec_date.year] += 1
            analysis['recording_months'][rec_date.month] += 1

        # Title companies
        title_company = header.get('Title_Company_Name', 'NA')
        if title_company != 'NA':
            analysis['title_companies'][title_company] += 1

        # Financing types
        financing = header.get('Type_Of_Financing', 'NA')
        if financing != 'NA':
            analysis['financing_types'][financing] += 1

        # Sale amounts
        sale_amount = parse_amount(header.get('Sale_Amount', 'NA'))
        if sale_amount is not None:
            analysis['sale_amounts'].append(sale_amount)

        # Loan details
        loan_details = header.get('Loan_Details', {})
        loan_amount = parse_amount(loan_details.get('Loan_Amount', 'NA'))
        if loan_amount is not None:
            analysis['loan_amounts'].append(loan_amount)
            analysis['has_loan_info'] += 1

        # Check for other info types
        if any(lien.get('Lien_Type') != 'NA' for lien in header.get('Lien_Details', [])):
            analysis['has_lien_info'] += 1

        if any(j.get('Judgement_Type') != 'NA' for j in header.get('Judgement_Details', [])):
            analysis['has_judgment_info'] += 1

        if any(t.get('Tax_Type') != 'NA' for t in header.get('Tax_Details', [])):
            analysis['has_tax_info'] += 1

        # Parties analysis
        for party in doc.get('Parties', []):
            role = party.get('Role', 'Unknown')
            analysis['party_roles'][role] += 1

            rel_status = party.get('Relationship_Status', 'NA')
            if rel_status != 'NA':
                analysis['party_relationships'][rel_status] += 1

        # Properties analysis
        for prop in doc.get('Properties', []):
            prop_type = prop.get('Property_Type', 'Unknown')
            analysis['property_types'][prop_type] += 1

            # Extract city from address
            address = prop.get('Property_Address', '')
            if address and address != 'NA':
                # Try to extract city (assumes format: "..., City, State Zip")
                parts = address.split(',')
                if len(parts) >= 2:
                    city = parts[-2].strip().split()[0] if parts[-2].strip() else 'Unknown'
                    analysis['cities'][city] += 1

            # APNs
            for apn_obj in prop.get('Assessors_Parcel_Numbers_Or_Parcel_Ids', []):
                apn = apn_obj.get('APN', 'NA')
                if apn != 'NA':
                    # Analyze APN pattern
                    pattern = re.sub(r'\d', '#', apn)
                    analysis['apn_patterns'][pattern] += 1

        # Legal descriptions
        for legal in doc.get('Legal_Descriptions', []):
            attrs = legal.get('Legal_Description_Attributes', {})
            if isinstance(attrs, dict):
                subdivision = attrs.get('Sub_Division', 'NA')
                if subdivision != 'NA':
                    analysis['subdivisions'][subdivision] += 1

        # Prior documents
        prior_docs = doc.get('Primary_Or_Prior_Document_Details', [])
        if any(pd.get('Primary_Or_Prior_Document_Name') != 'NA' for pd in prior_docs):
            analysis['has_prior_docs'] += 1

    return analysis

def generate_report(analysis):
    """Generate a comprehensive analysis report"""
    report = []

    report.append("# Wayne County Ohio Property Documents Analysis Report")
    report.append(f"\nTotal Documents Analyzed: {analysis['total_documents']}")
    report.append("=" * 80)

    # Document Types
    report.append("\n## Document Types Distribution")
    report.append("-" * 40)
    for doc_type, count in analysis['document_types'].most_common():
        percentage = (count / analysis['total_documents']) * 100
        report.append(f"{doc_type}: {count} ({percentage:.1f}%)")

    # Recording Years
    report.append("\n## Recording Years")
    report.append("-" * 40)
    for year, count in sorted(analysis['recording_years'].items()):
        report.append(f"{year}: {count} documents")

    # Party Roles
    report.append("\n## Party Roles Distribution")
    report.append("-" * 40)
    for role, count in analysis['party_roles'].most_common(15):
        report.append(f"{role}: {count}")

    # Party Relationships
    report.append("\n## Party Relationship Status")
    report.append("-" * 40)
    for rel, count in analysis['party_relationships'].most_common():
        report.append(f"{rel}: {count}")

    # Property Types
    report.append("\n## Property Types")
    report.append("-" * 40)
    for prop_type, count in analysis['property_types'].most_common():
        percentage = (count / sum(analysis['property_types'].values())) * 100
        report.append(f"{prop_type}: {count} ({percentage:.1f}%)")

    # Cities
    report.append("\n## Top 20 Cities")
    report.append("-" * 40)
    for city, count in analysis['cities'].most_common(20):
        report.append(f"{city}: {count}")

    # Financial Analysis
    report.append("\n## Financial Information")
    report.append("-" * 40)

    if analysis['sale_amounts']:
        amounts = [a for a in analysis['sale_amounts'] if a > 0]
        if amounts:
            report.append("Sale Amounts:")
            report.append(f"  - Documents with sale amount: {len(analysis['sale_amounts'])}")
            report.append(f"  - Average: ${sum(amounts)/len(amounts):,.2f}")
            report.append(f"  - Minimum: ${min(amounts):,.2f}")
            report.append(f"  - Maximum: ${max(amounts):,.2f}")

    if analysis['loan_amounts']:
        amounts = [a for a in analysis['loan_amounts'] if a > 0]
        if amounts:
            report.append("\nLoan Amounts:")
            report.append(f"  - Documents with loan amount: {len(analysis['loan_amounts'])}")
            report.append(f"  - Average: ${sum(amounts)/len(amounts):,.2f}")
            report.append(f"  - Minimum: ${min(amounts):,.2f}")
            report.append(f"  - Maximum: ${max(amounts):,.2f}")

    # Additional Information
    report.append("\n## Additional Document Information")
    report.append("-" * 40)
    report.append(f"Documents with loan information: {analysis['has_loan_info']}")
    report.append(f"Documents with lien information: {analysis['has_lien_info']}")
    report.append(f"Documents with judgment information: {analysis['has_judgment_info']}")
    report.append(f"Documents with tax information: {analysis['has_tax_info']}")
    report.append(f"Documents with prior document references: {analysis['has_prior_docs']}")

    # Title Companies
    if analysis['title_companies']:
        report.append("\n## Title Companies")
        report.append("-" * 40)
        for company, count in analysis['title_companies'].most_common(10):
            report.append(f"{company}: {count}")

    # Financing Types
    if analysis['financing_types']:
        report.append("\n## Financing Types")
        report.append("-" * 40)
        for f_type, count in analysis['financing_types'].most_common():
            report.append(f"{f_type}: {count}")

    # APN Patterns
    report.append("\n## APN (Assessor's Parcel Number) Patterns")
    report.append("-" * 40)
    for pattern, count in analysis['apn_patterns'].most_common(10):
        report.append(f"{pattern}: {count}")

    # Top Subdivisions
    report.append("\n## Top 20 Subdivisions")
    report.append("-" * 40)
    for subdivision, count in analysis['subdivisions'].most_common(20):
        report.append(f"{subdivision}: {count}")

    return "\n".join(report)

def main():
    # Load all JSON files
    print("Loading JSON files...")
    json_data = load_json_files('gt')
    print(f"Loaded {len(json_data)} JSON files")

    # Perform analysis
    print("Analyzing documents...")
    analysis = analyze_documents(json_data)

    # Generate report
    print("Generating report...")
    report = generate_report(analysis)

    # Save report
    with open('analysis_report.txt', 'w') as f:
        f.write(report)

    print("\nAnalysis complete! Report saved to 'analysis_report.txt'")

    # Also print to console
    print("\n" + "=" * 80)
    print(report)

if __name__ == "__main__":
    main()
