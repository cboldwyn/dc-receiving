"""
DC Receiving Tool v3.7
Extract and process transfer manifest data from Metrc PDFs and generate receiving worksheets

CHANGELOG:
v3.7 (2025-01-30)
- CLEANUP: Removed unused Enter Received Quantities tab
- CLEANUP: Removed debugging columns (ID Length, ID Valid)
- UI: Package List now hides index column
- UI: Reordered columns - Production Batch now after Package ID
- UI: Removed unused Volume and Strain columns
- EXPORT: Renamed ID to Distru ID in batch update export

v3.6 (2025-01-30)
- NEW: Batch Update Export for Distru - outputs Distru ID, Distru Batch Number, Expiration Date
- Distru Batch Number now uses Production Batch from manifest (the actual batch to import)
- Expiration Date calculated from Lab Testing Updated Date + 1 year
- Enhanced Distru Export tab with preview and clear export options
- Added Lab Testing Updated Date field from Distru CSV

v3.5 (2025-01-30)
- CRITICAL FIX: Package IDs now correctly capture all 24 characters
- Fixed bug where leading "1" was being skipped during extraction
- Added validation to ensure Package IDs are exactly 24 characters
- Added fallback to prepend "1" if 23-char ID starting with "A" is detected

v3.4 (2025-12-01)
- Added optional Distru Packages CSV integration
- Match METRC Package IDs to Distru Package Labels automatically
- Export Distru Import CSV with exact column format for Distru system
- Store Distru ID, Batch Number, and other metadata with each package
- New "Distru Export" tab when Distru CSV is uploaded

v3.3 (2025-11-19)
- Combined Batch, Quantity, and Sell-By into single column
- Layout: Batch on top, Qty with line below, Sell-By with line at bottom
- Smarter parenthesis filtering: only removes final category section
- Preserves product name parentheses like "Side Hustle (Flower)"
"""

import streamlit as st
import pandas as pd
import io
import re
from typing import List, Dict, Optional
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER

# ============================================================================
# CONFIGURATION
# ============================================================================

st.set_page_config(
    page_title="DC Receiving Tool v3.7",
    page_icon="📦",
    layout="wide"
)

VERSION = "3.7"

# CRITICAL RULE: All Package IDs MUST have exactly 24 characters
PACKAGE_ID_LENGTH = 24

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def calculate_expiration_date(lab_date_str):
    """
    Calculate expiration date by adding 1 year to lab testing date
    
    Args:
        lab_date_str: Date string in format YYYY-MM-DD or similar
        
    Returns:
        str: Expiration date in YYYY-MM-DD format, or empty string if invalid
    """
    if pd.isna(lab_date_str) or lab_date_str == '' or lab_date_str == 'nan':
        return ''
    
    try:
        # Parse the date (handles various formats)
        if isinstance(lab_date_str, str):
            # Try common formats
            for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%Y/%m/%d', '%m-%d-%Y']:
                try:
                    lab_date = datetime.strptime(lab_date_str.split()[0], fmt)
                    break
                except ValueError:
                    continue
            else:
                return ''
        elif isinstance(lab_date_str, datetime):
            lab_date = lab_date_str
        elif hasattr(lab_date_str, 'date'):  # pandas Timestamp
            lab_date = lab_date_str.to_pydatetime()
        else:
            return ''
        
        # Add 1 year (handle leap year edge case)
        try:
            expiration = lab_date.replace(year=lab_date.year + 1)
        except ValueError:
            # Feb 29 -> Feb 28
            expiration = lab_date.replace(year=lab_date.year + 1, day=28)
        
        return expiration.strftime('%Y-%m-%d')
    except Exception:
        return ''

# ============================================================================
# PDF EXTRACTION FUNCTIONS
# ============================================================================

def extract_text_from_pdf(pdf_file) -> str:
    """Extract text from uploaded PDF file"""
    try:
        import PyPDF2
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        st.error(f"Error reading PDF: {str(e)}")
        return ""

def extract_manifest_number(text: str) -> Optional[str]:
    """Extract manifest number from PDF text"""
    match = re.search(r'Manifest No\.\s+(\d+)', text)
    return match.group(1) if match else None

def extract_destination(text: str) -> Optional[str]:
    """Extract destination from PDF text"""
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if 'Destination' in line and i + 1 < len(lines):
            dest = lines[i + 1].strip()
            if dest and dest[0].isupper():
                return dest
    return None

def extract_originating_entity(text: str) -> Optional[str]:
    """Extract originating entity from PDF text"""
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if 'Originating' in line and i + 1 < len(lines):
            origin = lines[i + 1].strip()
            if origin and origin[0].isupper():
                return origin
    return None

def parse_distru_csv(uploaded_file) -> Dict[str, Dict]:
    """
    Parse Distru Packages CSV and create lookup dictionary
    
    Returns:
        Dictionary mapping Package Label (METRC ID) to Distru package data
        Example: {'1A406030006E731000695754': {'distru_id': '20604864', 'distru_product': '...', ...}}
    """
    try:
        # Read CSV
        df = pd.read_csv(uploaded_file)
        
        # Create lookup dictionary keyed by Package Label (METRC Package ID)
        distru_lookup = {}
        
        for _, row in df.iterrows():
            package_label = str(row.get('Package Label', '')).strip()
            
            if package_label:
                distru_lookup[package_label] = {
                    'distru_id': str(row.get('ID', '')),
                    'distru_product': str(row.get('Distru Product', '')),
                    'distru_batch_number': str(row.get('Distru Batch Number', '')),
                    'license_number': str(row.get('License Number', '')),
                    'location': str(row.get('Location', '')),
                    'expiration_date': str(row.get('Expiration Date', '')),
                    'harvest_date': str(row.get('Harvest Date', '')),
                    'description': str(row.get('Description', '')),
                    'quantity': str(row.get('Quantity', '')),
                    'lab_testing_date': str(row.get('Lab Testing Updated Date', ''))  # For expiration calc
                }
        
        return distru_lookup
        
    except Exception as e:
        st.error(f"Error parsing Distru CSV: {str(e)}")
        return {}

def extract_packages(text: str, distru_lookup: Optional[Dict] = None) -> List[Dict]:
    """Extract package information from manifest text using line-by-line parsing"""
    lines = text.split('\n')
    packages = []
    package_count = 0
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Look for package header
        if '. Package |' in line:
            if i + 1 < len(lines) and lines[i + 1].strip() in ['Accepted', 'Shipped']:
                package_count += 1
                i += 5  # Skip header lines
                
                package_data = extract_single_package(lines, i, package_count, distru_lookup)
                if package_data:
                    packages.append(package_data)
        
        i += 1
    
    return packages

def extract_single_package(lines: List[str], start_idx: int, package_num: int, distru_lookup: Optional[Dict] = None) -> Optional[Dict]:
    """Extract a single package starting from given line index"""
    package_data = {
        'package_number': package_num,
        'package_id': None,
        'item_name': None,
        'quantity_shipped': None,
        'production_batch': None,
        'item_details': {}
    }
    
    i = start_idx
    
    # FIXED v3.5: Collect ALL package ID parts including single digits like "1"
    # Package IDs are always 24 characters starting with "1A"
    # PDF extraction may split the ID across multiple lines (e.g., "1" on its own line)
    package_id_parts = []
    while i < len(lines):
        line = lines[i].strip()
        if 'Lab Test' in line:
            break
        # Include ALL alphanumeric parts - DO NOT skip short numeric lines
        # This fixes the bug where the leading "1" was being skipped
        if line and line.isalnum() and len(line) <= 24:
            package_id_parts.append(line)
        i += 1
    
    # Combine parts and validate - Package IDs MUST be exactly 24 characters
    raw_package_id = ''.join(package_id_parts)
    
    # Validate and extract the 24-character Package ID
    if len(raw_package_id) > PACKAGE_ID_LENGTH:
        # Too long - look for the standard 1A pattern and extract 24 chars
        match = re.search(r'(1A[A-Z0-9]{22})', raw_package_id)
        if match:
            package_data['package_id'] = match.group(1)
        else:
            # Fallback: take first 24 chars
            package_data['package_id'] = raw_package_id[:PACKAGE_ID_LENGTH]
    elif len(raw_package_id) == PACKAGE_ID_LENGTH:
        # Perfect - exactly 24 characters
        package_data['package_id'] = raw_package_id
    elif len(raw_package_id) == 23 and raw_package_id.startswith('A'):
        # Missing the leading "1" - prepend it
        package_data['package_id'] = '1' + raw_package_id
    else:
        # Unexpected length - use as-is but log warning
        package_data['package_id'] = raw_package_id
    
    # Skip to "Contains Retail IDs: No"
    while i < len(lines) and 'Contains Retail IDs' not in lines[i]:
        i += 1
    i += 1
    
    # Collect item name until "Shp:" or "Item Details"
    item_name_parts = []
    while i < len(lines):
        line = lines[i].strip()
        if 'Shp:' in line or 'Item Details' in line:
            break
        if line:
            item_name_parts.append(line)
        i += 1
    
    full_name = ' '.join(item_name_parts)
    
    # Clean item name - remove final category section with nested parentheses
    # Pattern: (Category (measurement)) at the end
    # Examples: (Topical (weight - each)), (Flower (packaged eighth - each))
    # Match final parenthetical with nested parens: space + ( + stuff + ( + stuff + ) + )
    final_category_pattern = r'\s+\([^)]*\([^)]*\)\)\s*$'
    cleaned = re.sub(final_category_pattern, '', full_name)
    
    # If no match, try simpler pattern for non-nested final parentheses at end
    if cleaned == full_name:
        # Match final simple parentheses: space + ( + stuff + ) at very end
        simple_pattern = r'\s+\([^(]*\)\s*$'
        # But only if it looks like a category (contains certain keywords)
        match = re.search(simple_pattern, full_name)
        if match and any(keyword in match.group().lower() for keyword in 
                        ['edible', 'extract', 'concentrate', 'weight', 'each', 'packaged']):
            cleaned = re.sub(simple_pattern, '', full_name)
    
    package_data['item_name'] = cleaned.strip()
    
    # Extract shipped quantity only
    if i < len(lines) and 'Shp:' in lines[i]:
        qty_lines = [lines[i]]
        for j in range(i+1, min(i+3, len(lines))):
            qty_lines.append(lines[j])
            if 'ea' in lines[j]:
                i = j + 1
                break
        
        qty_text = ' '.join(qty_lines)
        shp_match = re.search(r'Shp:\s*(\d+(?:\.\d+)?)', qty_text)
        if shp_match:
            package_data['quantity_shipped'] = float(shp_match.group(1))
    
    # Extract item details - Weight, Volume, Strain
    for j in range(i, min(len(lines), i + 20)):
        line = lines[j].strip()
        
        if line.startswith('Wgt:') or line.startswith('Weight:'):
            wgt_match = re.search(r'(\d+(?:\.\d+)?)\s*(g|kg|oz|lb)', line, re.IGNORECASE)
            if wgt_match:
                package_data['item_details']['weight'] = f"{wgt_match.group(1)} {wgt_match.group(2)}"
        
        if line.startswith('Vol:') or line.startswith('Volume:'):
            vol_match = re.search(r'(\d+(?:\.\d+)?)\s*(ml|l|fl\s*oz)', line, re.IGNORECASE)
            if vol_match:
                package_data['item_details']['volume'] = f"{vol_match.group(1)} {vol_match.group(2)}"
        
        if line.startswith('Strain:'):
            strain_match = re.search(r'Strain:\s*([^\|]+)', line)
            if strain_match:
                package_data['item_details']['strain'] = strain_match.group(1).strip()
    
    # Look for production batch
    for j in range(i, min(len(lines), i + 50)):
        if 'Source Production Batch' in lines[j]:
            if j + 1 < len(lines):
                batch_line = lines[j + 1].strip()
                if batch_line:
                    package_data['production_batch'] = batch_line
                else:
                    batch_match = re.search(r'Source Production Batch\s+([\w\-,]+)', lines[j])
                    if batch_match:
                        package_data['production_batch'] = batch_match.group(1)
            break
    
    # Add Distru data if available
    if distru_lookup and package_data['package_id']:
        distru_data = distru_lookup.get(package_data['package_id'])
        if distru_data:
            package_data['distru_id'] = distru_data.get('distru_id', '')
            package_data['distru_product'] = distru_data.get('distru_product', '')
            package_data['distru_batch_number'] = distru_data.get('distru_batch_number', '')
            package_data['license_number'] = distru_data.get('license_number', '')
            package_data['location'] = distru_data.get('location', '')
            package_data['expiration_date'] = distru_data.get('expiration_date', '')
            package_data['harvest_date'] = distru_data.get('harvest_date', '')
            package_data['description'] = distru_data.get('description', '')
            package_data['lab_testing_date'] = distru_data.get('lab_testing_date', '')
            # Calculate expiration from lab date + 1 year
            package_data['calculated_expiration'] = calculate_expiration_date(
                distru_data.get('lab_testing_date', '')
            )
            package_data['distru_matched'] = True
        else:
            # No match found - initialize empty fields
            package_data['distru_id'] = ''
            package_data['distru_product'] = ''
            package_data['distru_batch_number'] = ''
            package_data['license_number'] = ''
            package_data['location'] = ''
            package_data['expiration_date'] = ''
            package_data['harvest_date'] = ''
            package_data['description'] = ''
            package_data['lab_testing_date'] = ''
            package_data['calculated_expiration'] = ''
            package_data['distru_matched'] = False
    
    return package_data

# ============================================================================
# DATA PROCESSING FUNCTIONS
# ============================================================================

def packages_to_dataframe(packages: List[Dict]) -> pd.DataFrame:
    """Convert package list to DataFrame"""
    if not packages:
        return pd.DataFrame()
    
    rows = []
    for pkg in packages:
        row = {
            'Package #': pkg['package_number'],
            'Package ID': pkg['package_id'],
            'Production Batch': pkg['production_batch'],
            'Item Name': pkg['item_name'],
            'Qty Shipped': pkg['quantity_shipped'],
            'Weight': pkg['item_details'].get('weight', '')
        }
        rows.append(row)
    
    return pd.DataFrame(rows)

def generate_distru_export_csv(packages: List[Dict]) -> io.StringIO:
    """
    Generate Distru Import CSV with exact column format for FULL import
    
    Output columns (exact format required by Distru):
    - Distru ID
    - Package Number
    - Distru Product Name
    - License Number
    - Location Name
    - Distru Batch Number
    - Expiration Date
    - Harvest Date
    - Description
    - Bin Names (comma separated)
    """
    if not packages:
        return io.StringIO()
    
    rows = []
    for pkg in packages:
        row = {
            'Distru ID': pkg.get('distru_id', ''),
            'Package Number': pkg.get('package_id', ''),
            'Distru Product Name': pkg.get('distru_product', ''),
            'License Number': pkg.get('license_number', ''),
            'Location Name': pkg.get('location', ''),
            'Distru Batch Number': pkg.get('distru_batch_number', ''),
            'Expiration Date': pkg.get('expiration_date', ''),
            'Harvest Date': pkg.get('harvest_date', ''),
            'Description': pkg.get('description', ''),
            'Bin Names (comma separated)': ''  # Empty by default, user can fill in manually
        }
        rows.append(row)
    
    df = pd.DataFrame(rows)
    
    # Create CSV in memory
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)
    
    return csv_buffer


def generate_distru_batch_update_csv(packages: List[Dict]) -> io.StringIO:
    """
    Generate Distru Batch Update CSV - simplified format for updating batch numbers
    
    This uses:
    - Distru ID: Distru Package ID
    - Distru Batch Number: Production Batch from manifest (the NEW batch number to import)
    - Expiration Date: Calculated from Lab Testing Date + 1 year
    
    Output columns:
    - Distru ID
    - Distru Batch Number
    - Expiration Date
    """
    if not packages:
        return io.StringIO()
    
    rows = []
    for pkg in packages:
        # Only include packages that matched Distru AND have a production batch
        if pkg.get('distru_matched') and pkg.get('production_batch'):
            row = {
                'Distru ID': pkg.get('distru_id', ''),
                'Distru Batch Number': pkg.get('production_batch', ''),  # Use manifest's Production Batch
                'Expiration Date': pkg.get('calculated_expiration', '')  # Lab date + 1 year
            }
            rows.append(row)
    
    df = pd.DataFrame(rows)
    
    # Create CSV in memory
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)
    
    return csv_buffer

# ============================================================================
# PDF GENERATION FUNCTIONS
# ============================================================================

def generate_receiving_worksheet(manifest_num: str, origin: str, packages: List[Dict]) -> io.BytesIO:
    """Generate a receiving worksheet PDF from package data"""
    
    buffer = io.BytesIO()
    
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.5*inch,
        leftMargin=0.5*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch
    )
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#008B8B'),
        spaceAfter=4,
        alignment=TA_CENTER,
        leading=22
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Normal'],
        fontSize=12,
        textColor=colors.HexColor('#008B8B'),
        spaceAfter=12,
        alignment=TA_CENTER
    )
    
    story = []
    
    # Title and Subtitle
    title = Paragraph("HAVEN DISTRIBUTION", title_style)
    story.append(title)
    subtitle = Paragraph("Receiving Worksheet", subtitle_style)
    story.append(subtitle)
    story.append(Spacer(1, 0.15*inch))
    
    # Header Information - single line format
    header_table = Table(
        [[f'Manifest #:  {manifest_num}', f'From:  {origin}']],
        colWidths=[3.5*inch, 3.5*inch]
    )
    header_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    
    story.append(header_table)
    story.append(Spacer(1, 0.25*inch))
    
    # Package Table - combined Batch/Quantity/Sell-By column
    table_data = [['#', 'Item Name', 'Batch / Quantity / Sell-By']]
    
    # Add packages
    for pkg in packages:
        # Item name with package ID below (smaller font)
        item_with_id = Paragraph(
            f"{pkg['item_name']}<br/>"
            f"<font size=7>{pkg['package_id'][-8:]}</font>",
            styles['Normal']
        )
        
        # Combined cell: Batch, Quantity with line, Sell-By with line
        batch_val = pkg['production_batch'] or ''
        if len(batch_val) > 20:
            batch_val = batch_val[:20]
        
        qty_val = int(pkg['quantity_shipped']) if pkg['quantity_shipped'] else 0
        
        combined_text = Paragraph(
            f"{batch_val}<br/>"
            f"{qty_val} ea  _______<br/>"
            f"Sell-By: _______",
            styles['Normal']
        )
        
        table_data.append([
            str(pkg['package_number']),
            item_with_id,
            combined_text
        ])
    
    # Create table with new column widths
    pkg_table = Table(
        table_data,
        colWidths=[0.4*inch, 4.5*inch, 2.1*inch]
    )
    
    # Table style
    pkg_table.setStyle(TableStyle([
        # Header row
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#008B8B')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('TOPPADDING', (0, 0), (-1, 0), 12),
        
        # Data rows
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        ('ALIGN', (1, 1), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F0F0F0')]),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
    ]))
    
    story.append(pkg_table)
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer

# ============================================================================
# MAIN APPLICATION
# ============================================================================

def main():
    st.title(f"📦 DC Receiving Tool v{VERSION}")
    st.markdown("Process transfer manifests and generate receiving worksheets")
    
    # Sidebar
    st.sidebar.header("📄 Upload Manifest")
    uploaded_file = st.sidebar.file_uploader(
        "Upload Transfer Manifest PDF:",
        type=['pdf'],
        help="Upload a Metrc transfer manifest PDF"
    )
    
    # Optional Distru CSV uploader
    st.sidebar.markdown("---")
    st.sidebar.header("🔗 Distru Integration (Optional)")
    distru_csv = st.sidebar.file_uploader(
        "Upload Distru Packages CSV:",
        type=['csv'],
        help="Optional: Upload Distru packages CSV to match and export"
    )
    
    # Parse Distru CSV if uploaded
    distru_lookup = None
    if distru_csv:
        with st.spinner("Parsing Distru CSV..."):
            distru_lookup = parse_distru_csv(distru_csv)
            if distru_lookup:
                st.sidebar.success(f"✅ Loaded {len(distru_lookup)} Distru packages")
            else:
                st.sidebar.warning("⚠️ No Distru packages loaded")
    
    if uploaded_file:
        # Extract text from PDF
        with st.spinner("Reading PDF..."):
            pdf_text = extract_text_from_pdf(uploaded_file)
        
        if not pdf_text:
            st.error("Could not extract text from PDF")
            return
        
        # Extract manifest info
        manifest_num = extract_manifest_number(pdf_text)
        destination = extract_destination(pdf_text)
        origin = extract_originating_entity(pdf_text)
        
        # Display manifest info
        st.subheader("📋 Manifest Information")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Manifest Number", manifest_num or "Not Found")
        with col2:
            st.metric("From", origin or "Not Found")
        with col3:
            st.metric("To", destination or "Not Found")
        
        # Extract packages (with optional Distru matching)
        with st.spinner("Extracting package data..."):
            packages = extract_packages(pdf_text, distru_lookup)
        
        if not packages:
            st.warning("No packages found in manifest")
            return
        
        st.success(f"✅ Found {len(packages)} packages")
        
        # Show Distru matching stats if Distru CSV was uploaded
        if distru_lookup:
            matched_count = sum(1 for pkg in packages if pkg.get('distru_matched', False))
            st.info(f"🔗 Distru Matching: {matched_count}/{len(packages)} packages matched")
        
        # Convert to DataFrame
        df = packages_to_dataframe(packages)
        
        # Tabs for different views (add Distru Export if Distru CSV uploaded)
        tab_names = ["📊 Overview", "📋 Package List"]
        if distru_lookup:
            tab_names.append("🔗 Distru Export")
        
        tabs = st.tabs(tab_names)
        
        with tabs[0]:  # Overview
            st.subheader("📊 Manifest Overview")
            
            # Summary metrics
            total_packages = len(df)
            total_shipped = df['Qty Shipped'].sum() if 'Qty Shipped' in df.columns else 0
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Packages", f"{total_packages:,}")
            with col2:
                st.metric("Total Quantity Shipped", f"{total_shipped:,.0f} ea")
            
            st.markdown("---")
            
            # Generate worksheet button - prominent placement
            st.subheader("📄 Generate Receiving Worksheet")
            st.markdown("Create a printable worksheet for use during physical receiving")
            
            if st.button("📄 Generate Worksheet PDF", type="primary", use_container_width=True):
                with st.spinner("Generating worksheet..."):
                    try:
                        pdf_buffer = generate_receiving_worksheet(
                            manifest_num or "Unknown",
                            origin or "Unknown",
                            packages
                        )
                        
                        st.success("✅ Worksheet generated successfully!")
                        st.download_button(
                            label="📥 Download Worksheet PDF",
                            data=pdf_buffer,
                            file_name=f"receiving_worksheet_{manifest_num}.pdf",
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True
                        )
                    except Exception as e:
                        st.error(f"Error generating PDF: {str(e)}")
                        with st.expander("Show error details"):
                            st.exception(e)
            
            st.markdown("---")
            
            # Preview data
            st.subheader("📋 Package Preview")
            st.dataframe(
                df[['Package #', 'Item Name', 'Qty Shipped', 'Production Batch']],
                use_container_width=True,
                height=400
            )
        
        with tabs[1]:  # Package List
            st.subheader("📋 Complete Package List")
            
            st.dataframe(df, use_container_width=True, height=600, hide_index=True)
            
            # Download button
            csv = df.to_csv(index=False)
            st.download_button(
                "📥 Download Package List CSV",
                csv,
                f"manifest_{manifest_num}_packages.csv",
                "text/csv"
            )
        
        # Distru Export tab (only if Distru CSV was uploaded)
        if distru_lookup:
            with tabs[2]:  # Distru Export tab
                st.subheader("🔗 Distru Export Options")
                st.markdown("Export package data for Distru import")
                
                # Show matching summary
                matched_pkgs = [pkg for pkg in packages if pkg.get('distru_matched', False)]
                unmatched_pkgs = [pkg for pkg in packages if not pkg.get('distru_matched', False)]
                # Count how many matched packages have production batch
                matched_with_batch = [pkg for pkg in matched_pkgs if pkg.get('production_batch')]
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Total Packages", len(packages))
                with col2:
                    st.metric("Matched to Distru", len(matched_pkgs), 
                             delta=f"{len(matched_pkgs)/len(packages)*100:.1f}%" if packages else "0%")
                with col3:
                    st.metric("With Batch Info", len(matched_with_batch))
                with col4:
                    st.metric("Unmatched", len(unmatched_pkgs))
                
                # Show matched packages
                if matched_pkgs:
                    st.success(f"✅ {len(matched_pkgs)} packages matched successfully")
                    
                    with st.expander("View Matched Packages"):
                        matched_df = pd.DataFrame([{
                            'Package #': pkg['package_number'],
                            'METRC Package ID': pkg['package_id'],
                            'Distru ID': pkg.get('distru_id', ''),
                            'Distru Product': pkg.get('distru_product', ''),
                            'Production Batch': pkg.get('production_batch', ''),
                            'Lab Testing Date': pkg.get('lab_testing_date', ''),
                            'Calc. Expiration': pkg.get('calculated_expiration', '')
                        } for pkg in matched_pkgs])
                        st.dataframe(matched_df, use_container_width=True)
                
                # Show unmatched packages
                if unmatched_pkgs:
                    st.warning(f"⚠️ {len(unmatched_pkgs)} packages could not be matched")
                    
                    with st.expander("View Unmatched Packages"):
                        unmatched_df = pd.DataFrame([{
                            'Package #': pkg['package_number'],
                            'METRC Package ID': pkg['package_id'],
                            'Item Name': pkg['item_name']
                        } for pkg in unmatched_pkgs])
                        st.dataframe(unmatched_df, use_container_width=True)
                
                st.markdown("---")
                
                # ================================================================
                # BATCH UPDATE EXPORT (Primary - what user asked for)
                # ================================================================
                st.subheader("📤 Batch Update Export (Recommended)")
                st.markdown("""
                **Use this export to update Distru packages with batch numbers from this manifest.**
                
                Output format:
                - **ID** - Distru Package ID
                - **Distru Batch Number** - Production Batch from manifest
                - **Expiration Date** - Lab Testing Date + 1 year
                """)
                
                if len(matched_with_batch) > 0:
                    # Preview the batch update data
                    with st.expander("Preview Batch Update Data", expanded=True):
                        preview_df = pd.DataFrame([{
                            'ID': pkg.get('distru_id', ''),
                            'Distru Batch Number': pkg.get('production_batch', ''),
                            'Expiration Date': pkg.get('calculated_expiration', ''),
                            'Distru Product': pkg.get('distru_product', '')  # For reference only
                        } for pkg in matched_with_batch])
                        st.dataframe(preview_df, use_container_width=True)
                    
                    if st.button("📤 Generate Batch Update CSV", type="primary", use_container_width=True):
                        with st.spinner("Generating batch update export..."):
                            csv_buffer = generate_distru_batch_update_csv(packages)
                            
                            st.success(f"✅ Batch update export generated with {len(matched_with_batch)} packages!")
                            st.download_button(
                                label="📥 Download Batch Update CSV",
                                data=csv_buffer.getvalue(),
                                file_name=f"distru_batch_update_{manifest_num}.csv",
                                mime="text/csv",
                                type="primary",
                                use_container_width=True
                            )
                else:
                    st.warning("⚠️ No matched packages with production batch information available")
                
                st.markdown("---")
                
                # ================================================================
                # FULL DISTRU EXPORT (Secondary - original functionality)
                # ================================================================
                with st.expander("📦 Full Distru Export (All Fields)"):
                    st.markdown("""
                    Full export with all Distru fields:
                    - Distru ID, Package Number, Distru Product Name, License Number, Location Name
                    - Distru Batch Number, Expiration Date, Harvest Date, Description, Bin Names
                    """)
                    
                    if st.button("📤 Generate Full Distru Export CSV", use_container_width=True):
                        with st.spinner("Generating Distru export..."):
                            csv_buffer = generate_distru_export_csv(packages)
                            
                            st.success("✅ Distru export generated!")
                            st.download_button(
                                label="📥 Download Full Distru Import CSV",
                                data=csv_buffer.getvalue(),
                                file_name=f"distru_full_import_{manifest_num}.csv",
                                mime="text/csv",
                                use_container_width=True
                            )
    
    else:
        # Instructions
        st.info("👆 Upload a transfer manifest PDF to get started")
        
        st.markdown("""
        ### How to Use
        
        1. **Upload Manifest**: Upload a Metrc transfer manifest PDF
        2. **Review Overview**: Check manifest info and package count
        3. **Generate Worksheet**: Click button to create printable worksheet
        4. **Download & Print**: Download PDF and print for receiving
        5. **Optional**: Upload Distru CSV for batch number export
        
        ### ✨ What's New in v3.7
        
        - ✅ **Batch Update Export**: Distru ID, Batch Number, Expiration Date
        - ✅ **Production Batch**: Uses manifest's Production Batch as Distru Batch Number
        - ✅ **Expiration Date**: Auto-calculated from Lab Testing Date + 1 year
        - ✅ **Cleaner UI**: Removed unused tabs and debug columns
        
        ### Worksheet Features
        
        - Haven Distribution branding
        - All packages in same order as manifest
        - Verification lines inline with batch and quantity
        - Compact format - many packages per page
        - Last 8 digits of Package ID for reference
        """)
    
    # Version info in sidebar
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Version {VERSION}**")
    
    with st.sidebar.expander("📋 Changelog"):
        st.markdown("""
        **v3.7** (2025-01-30) 🆕
        - Removed unused Enter Received Quantities tab
        - Removed debug columns (ID Length, ID Valid)
        - Cleaner Package List (hidden index, reordered cols)
        - Export uses "Distru ID" column name
        
        **v3.6** (2025-01-30)
        - NEW: Batch Update Export (Distru ID, Batch, Expiration)
        - Uses Production Batch from manifest
        - Calculates Expiration = Lab Date + 1 year
        
        **v3.5** (2025-01-30) ⚠️ CRITICAL FIX
        - Package IDs now correctly capture all 24 characters
        - Fixed: Leading "1" was being skipped
        
        **v3.4** (2025-12-01)
        - Distru Packages CSV integration
        - Match METRC IDs to Distru labels
        - Export Distru Import CSV
        
        **v3.3** (2025-11-19)
        - Combined Batch/Qty/Sell-By into single column
        - Smart parenthesis filtering (keeps product parens)
        
        **v3.2** (2025-11-19)
        - Item names: remove from FIRST ( onward
        - Batch/qty lines truly inline (plain strings)
        - Quantity as whole numbers (no decimals)
        - Single-line items
        
        **v3.1** (2025-11-19)
        - Item names: remove last parentheses (not comma)
        - Batch truncates to 20 chars max
        - Verification lines inline (not below)
        - Better UI layout with Overview tab
        
        **v3.0** (2025-11-19)
        - Restored PDF worksheet generation
        - Professional worksheet layout
        - Haven Distribution branding
        """)

if __name__ == "__main__":
    main()