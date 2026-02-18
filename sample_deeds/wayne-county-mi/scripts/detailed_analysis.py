#!/usr/bin/env python3
"""
Detailed analysis of Wayne County property records JSON data.
Analyzes field completeness, data quality issues, and generates visualizations.
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd


class JSONAnalyzer:
    """Analyzes JSON files for data quality and patterns."""

    def __init__(self, json_dir: str):
        self.json_dir = Path(json_dir)
        self.data = []
        self.field_stats = defaultdict(lambda: {'total': 0, 'filled': 0, 'na': 0})
        self.field_values = defaultdict(list)
        self.issues = []

    def load_json_files(self) -> None:
        """Load all JSON files from the directory."""
        json_files = list(self.json_dir.glob("*.json"))
        print(f"Found {len(json_files)} JSON files to analyze")

        for file_path in json_files:
            try:
                with open(file_path) as f:
                    data = json.load(f)
                    data['_filename'] = file_path.name
                    self.data.append(data)
            except Exception as e:
                self.issues.append({
                    'file': file_path.name,
                    'issue': 'Failed to load JSON',
                    'error': str(e)
                })

    def analyze_field_completeness(self, obj: Any, path: str = "") -> None:
        """Recursively analyze field completeness in JSON structure."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                current_path = f"{path}.{key}" if path else key
                self.field_stats[current_path]['total'] += 1

                if isinstance(value, str):
                    if value.upper() == "NA" or value.strip() == "":
                        self.field_stats[current_path]['na'] += 1
                    else:
                        self.field_stats[current_path]['filled'] += 1
                        self.field_values[current_path].append(value)
                elif isinstance(value, (list, dict)):
                    if value:  # Non-empty
                        self.field_stats[current_path]['filled'] += 1
                    else:
                        self.field_stats[current_path]['na'] += 1
                    self.analyze_field_completeness(value, current_path)
                else:
                    self.field_stats[current_path]['filled'] += 1
                    self.field_values[current_path].append(str(value))

        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                self.analyze_field_completeness(item, f"{path}[{i}]")

    def check_data_quality_issues(self) -> None:
        """Check for various data quality issues."""
        for record in self.data:
            filename = record.get('_filename', 'Unknown')

            # Check date format consistency
            if 'Header' in record:
                header = record['Header']

                # Recording date format check
                rec_date = header.get('Recording_Date_And_Time', '')
                if rec_date and rec_date != 'NA':
                    if not self._is_valid_date_format(rec_date):
                        self.issues.append({
                            'file': filename,
                            'issue': 'Inconsistent date format',
                            'field': 'Recording_Date_And_Time',
                            'value': rec_date
                        })

                # Check for missing critical fields
                critical_fields = [
                    'Recording_File_Number', 'Document_Type',
                    'Recording_State', 'Recording_County'
                ]
                for field in critical_fields:
                    if field not in header or header[field] == 'NA':
                        self.issues.append({
                            'file': filename,
                            'issue': 'Missing critical field',
                            'field': field,
                            'value': header.get(field, 'MISSING')
                        })

            # Check property addresses
            if 'Properties' in record:
                for i, prop in enumerate(record['Properties']):
                    addr = prop.get('Property_Address', '')
                    if addr and addr != 'NA':
                        if not self._is_valid_address(addr):
                            self.issues.append({
                                'file': filename,
                                'issue': 'Potentially invalid address format',
                                'field': f'Properties[{i}].Property_Address',
                                'value': addr
                            })

            # Check for duplicate parties
            if 'Parties' in record:
                party_names = [
                    p.get('Name', '') for p in record['Parties']
                    if p.get('Name', '') != 'NA'
                ]
                duplicates = [
                    name for name, count in Counter(party_names).items()
                    if count > 1
                ]
                if duplicates:
                    self.issues.append({
                        'file': filename,
                        'issue': 'Duplicate party names',
                        'field': 'Parties',
                        'value': ', '.join(duplicates)
                    })

    def _is_valid_date_format(self, date_str: str) -> bool:
        """Check if date string follows expected formats."""
        # Common date patterns found in the data
        patterns = [
            r'^\d{1,2}-[A-Za-z]+-\d{4}',  # DD-Month-YYYY
            r'^\d{1,2}/\d{1,2}/\d{4}',     # MM/DD/YYYY
            r'^\d{4}-\d{2}-\d{2}'          # YYYY-MM-DD
        ]
        return any(re.match(pattern, date_str.strip()) for pattern in patterns)

    def _is_valid_address(self, addr: str) -> bool:
        """Basic validation for address format."""
        # Should contain numbers and letters, and common address indicators
        return bool(re.search(r'\d', addr) and re.search(r'[A-Za-z]', addr))

    def analyze_patterns(self) -> dict[str, Any]:
        """Analyze patterns in the data."""
        patterns = {
            'document_types': Counter(),
            'property_types': Counter(),
            'party_roles': Counter(),
            'relationship_statuses': Counter(),
            'cities': Counter(),
            'subdivisions': Counter(),
            'date_patterns': defaultdict(int)
        }

        for record in self.data:
            # Document types
            if 'Header' in record:
                doc_type = record['Header'].get('Document_Type', 'Unknown')
                if doc_type != 'NA':
                    patterns['document_types'][doc_type] += 1

                # Date patterns
                rec_date = record['Header'].get('Recording_Date_And_Time', '')
                if rec_date and rec_date != 'NA':
                    year_match = re.search(r'(\d{4})', rec_date)
                    if year_match:
                        year = year_match.group(1)
                        patterns['date_patterns'][year] += 1

            # Property types and locations
            if 'Properties' in record:
                for prop in record['Properties']:
                    prop_type = prop.get('Property_Type', 'Unknown')
                    if prop_type != 'NA':
                        patterns['property_types'][prop_type] += 1

            # Party roles and relationships
            if 'Parties' in record:
                for party in record['Parties']:
                    role = party.get('Role', 'Unknown')
                    if role != 'NA':
                        patterns['party_roles'][role] += 1

                    rel_status = party.get('Relationship_Status', 'Unknown')
                    if rel_status != 'NA':
                        patterns['relationship_statuses'][rel_status] += 1

            # Legal description patterns
            if 'Legal_Descriptions' in record:
                for desc in record['Legal_Descriptions']:
                    if isinstance(desc, dict) and 'Legal_Description_Attributes' in desc:
                        attrs = desc['Legal_Description_Attributes']
                        if isinstance(attrs, dict):
                            city = attrs.get('City', '')
                            if city and city != 'NA':
                                patterns['cities'][city] += 1

                            subdivision = attrs.get('Sub_Division', '')
                            if subdivision and subdivision != 'NA':
                                patterns['subdivisions'][subdivision] += 1

        return patterns

    def generate_visualizations(self) -> None:
        """Generate visualizations of key statistics."""
        # Set up the plotting style
        plt.style.use('seaborn-v0_8-darkgrid')
        plt.figure(figsize=(20, 15))

        # 1. Field Completeness Heatmap
        ax1 = plt.subplot(3, 2, 1)
        self._plot_field_completeness_heatmap(ax1)

        # 2. Document Type Distribution
        ax2 = plt.subplot(3, 2, 2)
        patterns = self.analyze_patterns()
        self._plot_document_types(ax2, patterns['document_types'])

        # 3. Data Quality Issues
        ax3 = plt.subplot(3, 2, 3)
        self._plot_data_quality_issues(ax3)

        # 4. Recording Year Distribution
        ax4 = plt.subplot(3, 2, 4)
        self._plot_year_distribution(ax4, patterns['date_patterns'])

        # 5. Party Roles Distribution
        ax5 = plt.subplot(3, 2, 5)
        self._plot_party_roles(ax5, patterns['party_roles'])

        # 6. Cities Distribution
        ax6 = plt.subplot(3, 2, 6)
        self._plot_cities(ax6, patterns['cities'])

        plt.suptitle('Wayne County Property Records Analysis', fontsize=16, y=0.995)
        plt.tight_layout()
        plt.savefig('property_records_analysis.png', dpi=300, bbox_inches='tight')
        plt.close()

        # Generate additional detailed visualizations
        self._generate_completeness_report()

    def _plot_field_completeness_heatmap(self, ax) -> None:
        """Plot heatmap of field completeness."""
        # Get top-level field completion rates
        top_fields = {}
        for field, stats in self.field_stats.items():
            if '.' not in field and '[' not in field:
                if stats['total'] > 0:
                    completion_rate = (stats['filled'] / stats['total']) * 100
                    top_fields[field] = completion_rate

        # Sort by completion rate
        sorted_fields = sorted(top_fields.items(), key=lambda x: x[1], reverse=True)[:20]

        fields = [f[0] for f in sorted_fields]
        rates = [f[1] for f in sorted_fields]

        # Create color map based on completion rate
        def get_color(r):
            if r < 25:
                return '#d73027'
            elif r < 50:
                return '#fee090'
            elif r < 75:
                return '#abd9e9'
            return '#4575b4'
        colors = [get_color(r) for r in rates]

        bars = ax.barh(fields, rates, color=colors)
        ax.set_xlabel('Completion Rate (%)')
        ax.set_title('Top-Level Field Completion Rates')
        ax.set_xlim(0, 100)

        # Add value labels
        for bar, rate in zip(bars, rates, strict=False):
            ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2,
                   f'{rate:.1f}%', va='center', fontsize=9)

    def _plot_document_types(self, ax, doc_types: Counter) -> None:
        """Plot document type distribution."""
        top_types = doc_types.most_common(10)
        types = [t[0] for t in top_types]
        counts = [t[1] for t in top_types]

        ax.bar(range(len(types)), counts, color='skyblue')
        ax.set_xticks(range(len(types)))
        ax.set_xticklabels(types, rotation=45, ha='right')
        ax.set_ylabel('Count')
        ax.set_title('Document Type Distribution (Top 10)')

    def _plot_data_quality_issues(self, ax) -> None:
        """Plot data quality issues summary."""
        issue_types = Counter(issue['issue'] for issue in self.issues)

        if issue_types:
            types = list(issue_types.keys())
            counts = list(issue_types.values())

            ax.bar(range(len(types)), counts, color='coral')
            ax.set_xticks(range(len(types)))
            ax.set_xticklabels(types, rotation=45, ha='right')
            ax.set_ylabel('Count')
            ax.set_title('Data Quality Issues by Type')
        else:
            ax.text(0.5, 0.5, 'No data quality issues found!',
                   ha='center', va='center', transform=ax.transAxes)
            ax.set_title('Data Quality Issues')

    def _plot_year_distribution(self, ax, year_data: dict[str, int]) -> None:
        """Plot recording year distribution."""
        if year_data:
            years = sorted(year_data.keys())
            counts = [year_data[y] for y in years]

            ax.plot(years, counts, marker='o', linewidth=2, markersize=8)
            ax.set_xlabel('Year')
            ax.set_ylabel('Number of Records')
            ax.set_title('Recording Year Distribution')
            ax.grid(True, alpha=0.3)

            # Rotate x labels if many years
            if len(years) > 10:
                ax.set_xticklabels(years, rotation=45)

    def _plot_party_roles(self, ax, roles: Counter) -> None:
        """Plot party roles distribution."""
        top_roles = roles.most_common(10)
        if top_roles:
            roles_list = [r[0] for r in top_roles]
            counts = [r[1] for r in top_roles]

            ax.pie(counts, labels=roles_list, autopct='%1.1f%%', startangle=90)
            ax.set_title('Party Roles Distribution (Top 10)')

    def _plot_cities(self, ax, cities: Counter) -> None:
        """Plot cities distribution."""
        top_cities = cities.most_common(10)
        if top_cities:
            city_names = [c[0] for c in top_cities]
            counts = [c[1] for c in top_cities]

            ax.barh(city_names, counts, color='lightgreen')
            ax.set_xlabel('Count')
            ax.set_title('Top 10 Cities in Property Records')

    def _generate_completeness_report(self) -> None:
        """Generate detailed completeness report."""
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 12))

        # Detailed field analysis
        all_fields = []
        for field, stats in self.field_stats.items():
            if stats['total'] > 0:
                all_fields.append({
                    'Field': field,
                    'Total': stats['total'],
                    'Filled': stats['filled'],
                    'NA': stats['na'],
                    'Completion_Rate': (stats['filled'] / stats['total']) * 100
                })

        df = pd.DataFrame(all_fields)
        df = df.sort_values('Completion_Rate', ascending=False)

        # Plot 1: Fields with lowest completion rates
        low_completion = df[df['Completion_Rate'] < 50].head(20)
        if not low_completion.empty:
            ax1.barh(low_completion['Field'], low_completion['Completion_Rate'], color='salmon')
            ax1.set_xlabel('Completion Rate (%)')
            ax1.set_title('Fields with Lowest Completion Rates (< 50%)')
            ax1.set_xlim(0, 50)
        else:
            ax1.text(0.5, 0.5, 'All fields have > 50% completion rate!',
                    ha='center', va='center', transform=ax1.transAxes)
            ax1.set_title('Fields with Lowest Completion Rates')

        # Plot 2: Nested field analysis
        nested_fields = df[df['Field'].str.contains(r'[\.\[]')]
        if not nested_fields.empty:
            # Group by parent field
            parent_completion = {}
            for _, row in nested_fields.iterrows():
                parent = row['Field'].split('.')[0].split('[')[0]
                if parent not in parent_completion:
                    parent_completion[parent] = []
                parent_completion[parent].append(row['Completion_Rate'])

            # Calculate average completion for parent fields
            parent_avg = {k: sum(v)/len(v) for k, v in parent_completion.items()}
            sorted_parents = sorted(parent_avg.items(), key=lambda x: x[1])[:15]

            parents = [p[0] for p in sorted_parents]
            avgs = [p[1] for p in sorted_parents]

            ax2.barh(parents, avgs, color='lightcoral')
            ax2.set_xlabel('Average Completion Rate (%)')
            ax2.set_title('Parent Fields with Lowest Average Nested Completion')
            ax2.set_xlim(0, 100)

        plt.tight_layout()
        plt.savefig('field_completeness_detailed.png', dpi=300, bbox_inches='tight')
        plt.close()

    def generate_report(self) -> None:
        """Generate comprehensive analysis report."""
        print("\n" + "="*80)
        print("WAYNE COUNTY PROPERTY RECORDS ANALYSIS REPORT")
        print("="*80)

        print(f"\nTotal JSON files analyzed: {len(self.data)}")
        print(f"Total data quality issues found: {len(self.issues)}")

        # Field completeness summary
        print("\n" + "-"*50)
        print("FIELD COMPLETENESS SUMMARY")
        print("-"*50)

        total_fields = len(self.field_stats)
        high_completion = sum(1 for f, s in self.field_stats.items()
                            if s['total'] > 0 and (s['filled'] / s['total']) >= 0.8)
        low_completion = sum(1 for f, s in self.field_stats.items()
                           if s['total'] > 0 and (s['filled'] / s['total']) < 0.2)

        print(f"Total unique fields: {total_fields}")
        print(f"High completion fields (>80%): {high_completion}")
        print(f"Low completion fields (<20%): {low_completion}")

        # Most commonly filled fields
        print("\nMost Commonly Filled Fields:")
        filled_fields = [(f, (s['filled'] / s['total']) * 100)
                        for f, s in self.field_stats.items()
                        if s['total'] > 0]
        filled_fields.sort(key=lambda x: x[1], reverse=True)

        for field, rate in filled_fields[:10]:
            print(f"  - {field}: {rate:.1f}%")

        # Most commonly empty fields
        print("\nMost Commonly Empty Fields:")
        empty_fields = [(f, (s['na'] / s['total']) * 100)
                       for f, s in self.field_stats.items()
                       if s['total'] > 0]
        empty_fields.sort(key=lambda x: x[1], reverse=True)

        for field, rate in empty_fields[:10]:
            print(f"  - {field}: {rate:.1f}% NA")

        # Data quality issues summary
        print("\n" + "-"*50)
        print("DATA QUALITY ISSUES SUMMARY")
        print("-"*50)

        issue_summary = Counter(issue['issue'] for issue in self.issues)
        for issue_type, count in issue_summary.most_common():
            print(f"  - {issue_type}: {count} occurrences")

        # Pattern analysis
        patterns = self.analyze_patterns()

        print("\n" + "-"*50)
        print("DATA PATTERNS")
        print("-"*50)

        print(f"\nDocument Types: {len(patterns['document_types'])}")
        for doc_type, count in patterns['document_types'].most_common(5):
            print(f"  - {doc_type}: {count}")

        print(f"\nProperty Types: {len(patterns['property_types'])}")
        for prop_type, count in patterns['property_types'].most_common(5):
            print(f"  - {prop_type}: {count}")

        print(f"\nTop Cities: {len(patterns['cities'])}")
        for city, count in patterns['cities'].most_common(5):
            print(f"  - {city}: {count}")

        # Save detailed results to CSV
        self._save_detailed_results()

    def _save_detailed_results(self) -> None:
        """Save detailed analysis results to CSV files."""
        # Field statistics
        field_data = []
        for field, stats in self.field_stats.items():
            if stats['total'] > 0:
                field_data.append({
                    'Field': field,
                    'Total_Occurrences': stats['total'],
                    'Filled_Count': stats['filled'],
                    'NA_Count': stats['na'],
                    'Completion_Rate_%': (stats['filled'] / stats['total']) * 100,
                    'NA_Rate_%': (stats['na'] / stats['total']) * 100
                })

        df_fields = pd.DataFrame(field_data)
        df_fields = df_fields.sort_values('Completion_Rate_%', ascending=False)
        df_fields.to_csv('field_statistics.csv', index=False)

        # Data quality issues
        if self.issues:
            df_issues = pd.DataFrame(self.issues)
            df_issues.to_csv('data_quality_issues.csv', index=False)

        # Value frequency analysis for key fields
        value_analysis = []
        key_fields = ['Header.Document_Type', 'Properties[0].Property_Type',
                     'Header.Recording_State', 'Header.Recording_County']

        for field in key_fields:
            if field in self.field_values:
                value_counts = Counter(self.field_values[field])
                for value, count in value_counts.most_common(20):
                    value_analysis.append({
                        'Field': field,
                        'Value': value,
                        'Count': count,
                        'Percentage': (count / len(self.field_values[field])) * 100
                    })

        if value_analysis:
            df_values = pd.DataFrame(value_analysis)
            df_values.to_csv('field_value_frequencies.csv', index=False)

        print("\n✓ Detailed results saved to CSV files:")
        print("  - field_statistics.csv")
        print("  - data_quality_issues.csv")
        print("  - field_value_frequencies.csv")


def main():
    """Main function to run the analysis."""
    # Set up the analyzer
    analyzer = JSONAnalyzer('gt')

    print("Starting Wayne County Property Records Analysis...")
    print("-" * 50)

    # Load and analyze data
    print("Loading JSON files...")
    analyzer.load_json_files()

    print("Analyzing field completeness...")
    for record in analyzer.data:
        analyzer.analyze_field_completeness(record)

    print("Checking data quality issues...")
    analyzer.check_data_quality_issues()

    print("Generating visualizations...")
    analyzer.generate_visualizations()

    print("Generating report...")
    analyzer.generate_report()

    print("\n✓ Analysis complete!")
    print("✓ Visualizations saved:")
    print("  - property_records_analysis.png")
    print("  - field_completeness_detailed.png")


if __name__ == "__main__":
    main()
