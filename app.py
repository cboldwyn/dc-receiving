"""
DC Receiving Tool v3.9
Extract and process transfer manifest data from Metrc PDFs and generate receiving worksheets

CHANGELOG:
v3.9 (2026-03-04)
- NEW: Manual Batch Entry table in Distru Export tab
- Packages with missing or aggregate batches can now have batch number + expiration date entered manually
- Manual entries are merged with auto-extracted batches when generating the Batch Update CSV
- Expiration date pre-filled from Lab Testing Date + 1 year when available
- Session state preserves manual entries until a new manifest is uploaded

v3.8 (2025-03-04)
- FIX: Production Batch cleansing - aggregate batches (containing commas) are now ignored
- FIX: Missing Production Batch leaves Batch Number blank but still captures expiration date
- Expiration date logic is unaffected - always calculated from Lab Testing Date + 1 year

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
    page_title="DC Receiving Tool v3.9",
    page_icon="📦",
    layout="wide"
)

VERSION = "3.9"

# CRITICAL RULE: All Package IDs MUST have exactly 24 characters
PACKAGE_ID_LENGTH = 24

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def calculate_expiration_date(lab_date_str):
    if pd.isna(lab_date_str) or lab_date_str == '' or lab_date_str == 'nan':
        return ''
    try:
        if isinstance(lab_date_str, str):
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
        elif hasattr(lab_date_str, 'date'):
            lab_date = lab_date_str.to_pydatetime()
        else:
            return ''
        try:
            expiration = lab_date.replace(year=lab_date.year + 1)
        except ValueError:
            expiration = lab_date.replace(year=lab_date.year + 1, day=28)
        return expiration.strftime('%Y-%m-%d')
    except Exception:
        return ''


def is_valid_production_batch(batch_str: str) -> bool:
    if not batch_str or batch_str.strip() == '':
        return False
    if ',' in batch_str:
        return False
    return True

# ============================================================================
# PDF EXTRACTION FUNCTIONS
# ============================================================================

def extract_text_from_pdf(pdf_file) -> str:
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
    match = re.search(r'Manifest No\.\s+(\d+)', text)
    return match.group(1) if match else None


def extract_destination(text: str) -> Optional[str]:
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if 'Destination' in line and i + 1 < len(lines):
            dest = lines[i + 1].strip()
            if dest and dest[0].isupper():
                return dest
    return None


def extract_originating_entity(text: str) -> Optional[str]:
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if 'Originating' in line and i + 1 < len(lines):
            origin = lines[i + 1].strip()
            if origin and origin[0].isupper():
                return origin
    return None


def parse_distru_csv(uploaded_file) -> Dict[str, Dict]:
    try:
        df = pd.read_csv(uploaded_file)
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
                    'lab_testing_date': str(row.get('Lab Testing Updated Date', ''))
                }
        return distru_lookup
    except Exception as e:
        st.error(f"Error parsing Distru CSV: {str(e)}")
        return {}


def extract_packages(text: str, distru_lookup: Optional[Dict] = None) -> List[Dict]:
    lines = text.split('\n')
    packages = []
    package_count = 0
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if '. Package |' in line:
            if i + 1 < len(lines) and lines[i + 1].strip() in ['Accepted', 'Shipped']:
                package_count += 1
                i += 5
                package_data = extract_single_package(lines, i, package_count, distru_lookup)
                if package_data:
                    packages.append(package_data)
        i += 1
    return packages


def extract_single_package(lines: List[str], start_idx: int, package_num: int, distru_lookup: Optional[Dict] = None) -> Optional[Dict]:
    package_data = {
        'package_number': package_num,
        'package_id': None,
        'item_name': None,
        'quantity_shipped': None,
        'production_batch': None,
        'production_batch_status': 'none',  # 'none' | 'aggregate' | 'valid'
        'item_details': {}
    }

    i = start_idx

    package_id_parts = []
    while i < len(lines):
        line = lines[i].strip()
        if 'Lab Test' in line:
            break
        if line and line.isalnum() and len(line) <= 24:
            package_id_parts.append(line)
        i += 1

    raw_package_id = ''.join(package_id_parts)
    if len(raw_package_id) > PACKAGE_ID_LENGTH:
        match = re.search(r'(1A[A-Z0-9]{22})', raw_package_id)
        if match:
            package_data['package_id'] = match.group(1)
        else:
            package_data['package_id'] = raw_package_id[:PACKAGE_ID_LENGTH]
    elif len(raw_package_id) == PACKAGE_ID_LENGTH:
        package_data['package_id'] = raw_package_id
    elif len(raw_package_id) == 23 and raw_package_id.startswith('A'):
        package_data['package_id'] = '1' + raw_package_id
    else:
        package_data['package_id'] = raw_package_id

    while i < len(lines) and 'Contains Retail IDs' not in lines[i]:
        i += 1
    i += 1

    item_name_parts = []
    while i < len(lines):
        line = lines[i].strip()
        if 'Shp:' in line or 'Item Details' in line:
            break
        if line:
            item_name_parts.append(line)
        i += 1

    full_name = ' '.join(item_name_parts)
    final_category_pattern = r'\s+\([^)]*\([^)]*\)\)\s*$'
    cleaned = re.sub(final_category_pattern, '', full_name)
    if cleaned == full_name:
        simple_pattern = r'\s+\([^(]*\)\s*$'
        match = re.search(simple_pattern, full_name)
        if match and any(keyword in match.group().lower() for keyword in
                        ['edible', 'extract', 'concentrate', 'weight', 'each', 'packaged']):
            cleaned = re.sub(simple_pattern, '', full_name)
    package_data['item_name'] = cleaned.strip()

    if i < len(lines) and 'Shp:' in lines[i]:
        qty_lines = [lines[i]]
        for j in range(i + 1, min(i + 3, len(lines))):
            qty_lines.append(lines[j])
            if 'ea' in lines[j]:
                i = j + 1
                break
        qty_text = ' '.join(qty_lines)
        shp_match = re.search(r'Shp:\s*(\d+(?:\.\d+)?)', qty_text)
        if shp_match:
            package_data['quantity_shipped'] = float(shp_match.group(1))

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

    # v3.8: Production Batch extraction with cleansing
    for j in range(i, min(len(lines), i + 50)):
        if 'Source Production Batch' in lines[j]:
            raw_batch = None
            if j + 1 < len(lines):
                next_line = lines[j + 1].strip()
                if next_line:
                    raw_batch = next_line
                else:
                    batch_match = re.search(r'Source Production Batch\s+([\w\-,]+)', lines[j])
                    if batch_match:
                        raw_batch = batch_match.group(1)

            if raw_batch and ',' in raw_batch:
                package_data['production_batch'] = None
                package_data['production_batch_status'] = 'aggregate'
            elif is_valid_production_batch(raw_batch):
                package_data['production_batch'] = raw_batch
                package_data['production_batch_status'] = 'valid'
            else:
                package_data['production_batch'] = None
                package_data['production_batch_status'] = 'none'
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
            package_data['calculated_expiration'] = calculate_expiration_date(
                distru_data.get('lab_testing_date', '')
            )
            package_data['distru_matched'] = True
        else:
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
    if not packages:
        return pd.DataFrame()
    rows = []
    for pkg in packages:
        row = {
            'Package #': pkg['package_number'],
            'Package ID': pkg['package_id'],
            'Production Batch': pkg['production_batch'] or '',
            'Item Name': pkg['item_name'],
            'Qty Shipped': pkg['quantity_shipped'],
            'Weight': pkg['item_details'].get('weight', '')
        }
        rows.append(row)
    return pd.DataFrame(rows)


def generate_distru_export_csv(packages: List[Dict]) -> io.StringIO:
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
            'Bin Names (comma separated)': ''
        }
        rows.append(row)
    df = pd.DataFrame(rows)
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)
    return csv_buffer


def generate_distru_batch_update_csv(packages: List[Dict], manual_overrides: Dict[str, Dict] = None) -> tuple:
    """
    Generate Distru Batch Update CSV merging auto-extracted and manual batch entries.

    v3.9: Accepts manual_overrides dict keyed by package_id.
    Only packages matched to Distru are included.

    Returns:
        tuple: (csv_buffer, row_count)
    """
    if not packages:
        return io.StringIO(), 0

    manual_overrides = manual_overrides or {}
    rows = []

    for pkg in packages:
        if not pkg.get('distru_matched'):
            continue

        pkg_id = pkg.get('package_id', '')
        distru_id = pkg.get('distru_id', '')

        batch_to_use = None
        expiration_to_use = None

        if pkg.get('production_batch'):
            # Auto-extracted valid single batch
            batch_to_use = pkg['production_batch']
            expiration_to_use = pkg.get('calculated_expiration', '')
        elif pkg_id in manual_overrides:
            # Manual override
            override = manual_overrides[pkg_id]
            batch_to_use = override.get('batch', '').strip()
            expiration_to_use = override.get('expiration', '').strip()
            if not batch_to_use:
                continue

        if batch_to_use:
            rows.append({
                'Distru ID': distru_id,
                'Distru Batch Number': batch_to_use,
                'Expiration Date': expiration_to_use or ''
            })

    df = pd.DataFrame(rows)
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)
    return csv_buffer, len(rows)

# ============================================================================
# PDF GENERATION FUNCTIONS
# ============================================================================

def generate_receiving_worksheet(manifest_num: str, origin: str, packages: List[Dict]) -> io.BytesIO:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch
    )
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
    story.append(Paragraph("HAVEN DISTRIBUTION", title_style))
    story.append(Paragraph("Receiving Worksheet", subtitle_style))
    story.append(Spacer(1, 0.15 * inch))

    header_table = Table(
        [[f'Manifest #:  {manifest_num}', f'From:  {origin}']],
        colWidths=[3.5 * inch, 3.5 * inch]
    )
    header_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.25 * inch))

    table_data = [['#', 'Item Name', 'Batch / Quantity / Sell-By']]
    for pkg in packages:
        item_with_id = Paragraph(
            f"{pkg['item_name']}<br/>"
            f"<font size=7>{pkg['package_id'][-8:]}</font>",
            styles['Normal']
        )
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
        table_data.append([str(pkg['package_number']), item_with_id, combined_text])

    pkg_table = Table(table_data, colWidths=[0.4 * inch, 4.5 * inch, 2.1 * inch])
    pkg_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#008B8B')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('TOPPADDING', (0, 0), (-1, 0), 12),
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
    doc.build(story)
    buffer.seek(0)
    return buffer

# ============================================================================
# MAIN APPLICATION
# ============================================================================

def main():
    st.title(f"📦 DC Receiving Tool v{VERSION}")
    st.markdown("Process transfer manifests and generate receiving worksheets")

    st.sidebar.header("📄 Upload Manifest")
    uploaded_file = st.sidebar.file_uploader(
        "Upload Transfer Manifest PDF:",
        type=['pdf'],
        help="Upload a Metrc transfer manifest PDF"
    )

    st.sidebar.markdown("---")
    st.sidebar.header("🔗 Distru Integration (Optional)")
    distru_csv = st.sidebar.file_uploader(
        "Upload Distru Packages CSV:",
        type=['csv'],
        help="Optional: Upload Distru packages CSV to match and export"
    )

    # Clear manual overrides when a new manifest is uploaded
    if 'last_manifest_name' not in st.session_state:
        st.session_state['last_manifest_name'] = None
    if uploaded_file and uploaded_file.name != st.session_state['last_manifest_name']:
        st.session_state['last_manifest_name'] = uploaded_file.name
        st.session_state['manual_batch_overrides'] = {}
    if 'manual_batch_overrides' not in st.session_state:
        st.session_state['manual_batch_overrides'] = {}

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
        with st.spinner("Reading PDF..."):
            pdf_text = extract_text_from_pdf(uploaded_file)

        if not pdf_text:
            st.error("Could not extract text from PDF")
            return

        manifest_num = extract_manifest_number(pdf_text)
        destination = extract_destination(pdf_text)
        origin = extract_originating_entity(pdf_text)

        st.subheader("📋 Manifest Information")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Manifest Number", manifest_num or "Not Found")
        with col2:
            st.metric("From", origin or "Not Found")
        with col3:
            st.metric("To", destination or "Not Found")

        with st.spinner("Extracting package data..."):
            packages = extract_packages(pdf_text, distru_lookup)

        if not packages:
            st.warning("No packages found in manifest")
            return

        st.success(f"✅ Found {len(packages)} packages")

        # Batch status summary
        valid_batch_count = sum(1 for p in packages if p.get('production_batch_status') == 'valid')
        aggregate_count   = sum(1 for p in packages if p.get('production_batch_status') == 'aggregate')
        no_batch_count    = sum(1 for p in packages if p.get('production_batch_status') == 'none')
        needs_manual      = aggregate_count + no_batch_count

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("✅ Valid Batches", valid_batch_count)
        with col2:
            st.metric("⚠️ Aggregate (skipped)", aggregate_count)
        with col3:
            st.metric("❌ No Batch", no_batch_count)

        if needs_manual > 0:
            st.info(f"✏️ {needs_manual} package(s) need manual batch entry — see the **Distru Export** tab.")

        if distru_lookup:
            matched_count = sum(1 for pkg in packages if pkg.get('distru_matched', False))
            st.info(f"🔗 Distru Matching: {matched_count}/{len(packages)} packages matched")

        df = packages_to_dataframe(packages)

        tab_names = ["📊 Overview", "📋 Package List"]
        if distru_lookup:
            tab_names.append("🔗 Distru Export")

        tabs = st.tabs(tab_names)

        # ====================================================================
        # TAB 0: Overview
        # ====================================================================
        with tabs[0]:
            st.subheader("📊 Manifest Overview")
            total_packages = len(df)
            total_shipped = df['Qty Shipped'].sum() if 'Qty Shipped' in df.columns else 0
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Packages", f"{total_packages:,}")
            with col2:
                st.metric("Total Quantity Shipped", f"{total_shipped:,.0f} ea")

            st.markdown("---")
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
            st.subheader("📋 Package Preview")
            st.dataframe(
                df[['Package #', 'Item Name', 'Qty Shipped', 'Production Batch']],
                use_container_width=True,
                height=400
            )

        # ====================================================================
        # TAB 1: Package List
        # ====================================================================
        with tabs[1]:
            st.subheader("📋 Complete Package List")
            st.dataframe(df, use_container_width=True, height=600, hide_index=True)
            csv = df.to_csv(index=False)
            st.download_button(
                "📥 Download Package List CSV",
                csv,
                f"manifest_{manifest_num}_packages.csv",
                "text/csv"
            )

        # ====================================================================
        # TAB 2: Distru Export
        # ====================================================================
        if distru_lookup:
            with tabs[2]:
                st.subheader("🔗 Distru Export Options")

                matched_pkgs       = [pkg for pkg in packages if pkg.get('distru_matched', False)]
                unmatched_pkgs     = [pkg for pkg in packages if not pkg.get('distru_matched', False)]
                matched_with_batch = [pkg for pkg in matched_pkgs if pkg.get('production_batch')]
                needs_manual_pkgs  = [pkg for pkg in matched_pkgs if not pkg.get('production_batch')]

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Total Packages", len(packages))
                with col2:
                    st.metric("Matched to Distru", len(matched_pkgs),
                             delta=f"{len(matched_pkgs)/len(packages)*100:.1f}%" if packages else "0%")
                with col3:
                    st.metric("Auto Batch ✅", len(matched_with_batch))
                with col4:
                    st.metric("Need Manual Entry ✏️", len(needs_manual_pkgs))

                if matched_pkgs:
                    st.success(f"✅ {len(matched_pkgs)} packages matched to Distru")
                    with st.expander("View Matched Packages"):
                        matched_df = pd.DataFrame([{
                            'Package #': pkg['package_number'],
                            'METRC Package ID': pkg['package_id'],
                            'Distru ID': pkg.get('distru_id', ''),
                            'Distru Product': pkg.get('distru_product', ''),
                            'Batch Status': pkg.get('production_batch_status', 'none'),
                            'Production Batch': pkg.get('production_batch') or '(none / aggregate)',
                            'Lab Testing Date': pkg.get('lab_testing_date', ''),
                            'Calc. Expiration': pkg.get('calculated_expiration', '')
                        } for pkg in matched_pkgs])
                        st.dataframe(matched_df, use_container_width=True)

                if unmatched_pkgs:
                    st.warning(f"⚠️ {len(unmatched_pkgs)} packages could not be matched to Distru")
                    with st.expander("View Unmatched Packages"):
                        unmatched_df = pd.DataFrame([{
                            'Package #': pkg['package_number'],
                            'METRC Package ID': pkg['package_id'],
                            'Item Name': pkg['item_name']
                        } for pkg in unmatched_pkgs])
                        st.dataframe(unmatched_df, use_container_width=True)

                st.markdown("---")

                # ============================================================
                # MANUAL BATCH ENTRY
                # ============================================================
                if needs_manual_pkgs:
                    st.subheader("✏️ Manual Batch Entry")
                    st.markdown(
                        "The packages below had **no batch number** or an **aggregate batch** in the manifest. "
                        "Enter the correct **Batch Number** and **Expiration Date** for each, then click "
                        "**Save Manual Entries**. These will be included in the Batch Update CSV."
                    )

                    manual_rows = []
                    for pkg in needs_manual_pkgs:
                        pkg_id = pkg.get('package_id', '')
                        saved = st.session_state['manual_batch_overrides'].get(pkg_id, {})
                        manual_rows.append({
                            'Package #': pkg['package_number'],
                            'Item Name': pkg.get('item_name', ''),
                            'METRC ID (last 8)': pkg_id[-8:] if pkg_id else '',
                            'Distru ID': pkg.get('distru_id', ''),
                            'Batch Status': pkg.get('production_batch_status', 'none'),
                            'Batch Number': saved.get('batch', ''),
                            'Expiration Date (YYYY-MM-DD)': saved.get('expiration', pkg.get('calculated_expiration', ''))
                        })

                    manual_df = pd.DataFrame(manual_rows)

                    edited_df = st.data_editor(
                        manual_df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            'Package #':               st.column_config.NumberColumn(width='small'),
                            'Item Name':               st.column_config.TextColumn(width='large', disabled=True),
                            'METRC ID (last 8)':       st.column_config.TextColumn(width='medium', disabled=True),
                            'Distru ID':               st.column_config.TextColumn(width='small', disabled=True),
                            'Batch Status':            st.column_config.TextColumn(width='small', disabled=True),
                            'Batch Number':            st.column_config.TextColumn('✏️ Batch Number', width='medium'),
                            'Expiration Date (YYYY-MM-DD)': st.column_config.TextColumn('✏️ Expiration Date', width='medium'),
                        },
                        key="manual_batch_editor"
                    )

                    if st.button("💾 Save Manual Entries", type="secondary"):
                        saved_count = 0
                        for i, row in edited_df.iterrows():
                            pkg = needs_manual_pkgs[i]
                            pkg_id = pkg.get('package_id', '')
                            batch_val = str(row.get('Batch Number', '')).strip()
                            exp_val = str(row.get('Expiration Date (YYYY-MM-DD)', '')).strip()
                            if batch_val:
                                st.session_state['manual_batch_overrides'][pkg_id] = {
                                    'batch': batch_val,
                                    'expiration': exp_val
                                }
                                saved_count += 1
                            else:
                                st.session_state['manual_batch_overrides'].pop(pkg_id, None)
                        st.success(f"✅ Saved {saved_count} manual batch entr{'y' if saved_count == 1 else 'ies'}")

                    saved_manual_count = len([
                        pkg for pkg in needs_manual_pkgs
                        if st.session_state['manual_batch_overrides'].get(
                            pkg.get('package_id', ''), {}
                        ).get('batch', '')
                    ])
                    if saved_manual_count > 0:
                        st.info(f"📝 {saved_manual_count} manual batch entr{'y' if saved_manual_count == 1 else 'ies'} saved and ready for export")

                    st.markdown("---")

                # ============================================================
                # BATCH UPDATE EXPORT
                # ============================================================
                st.subheader("📤 Batch Update Export")
                st.markdown("""
                **Updates Distru packages with batch numbers from this manifest.**

                Output columns: **Distru ID** | **Distru Batch Number** | **Expiration Date**

                > Auto-extracted batches (single, non-aggregate) are always included.
                > Manual entries above are merged in when saved.
                > Packages not matched to Distru are always excluded.
                """)

                manual_overrides = st.session_state.get('manual_batch_overrides', {})
                manual_ready = len([
                    pkg for pkg in needs_manual_pkgs
                    if manual_overrides.get(pkg.get('package_id', ''), {}).get('batch', '')
                ])
                total_export_count = len(matched_with_batch) + manual_ready

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Auto Batches", len(matched_with_batch))
                with col2:
                    st.metric("Manual Batches", manual_ready)
                with col3:
                    st.metric("Total for Export", total_export_count)

                if total_export_count > 0:
                    with st.expander("Preview Batch Update Data", expanded=True):
                        preview_rows = []
                        for pkg in matched_with_batch:
                            preview_rows.append({
                                'Source': '🤖 Auto',
                                'Distru ID': pkg.get('distru_id', ''),
                                'Item': pkg.get('distru_product', '') or pkg.get('item_name', ''),
                                'Distru Batch Number': pkg.get('production_batch', ''),
                                'Expiration Date': pkg.get('calculated_expiration', '')
                            })
                        for pkg in needs_manual_pkgs:
                            pkg_id = pkg.get('package_id', '')
                            override = manual_overrides.get(pkg_id, {})
                            batch_val = override.get('batch', '').strip()
                            if batch_val:
                                preview_rows.append({
                                    'Source': '✏️ Manual',
                                    'Distru ID': pkg.get('distru_id', ''),
                                    'Item': pkg.get('distru_product', '') or pkg.get('item_name', ''),
                                    'Distru Batch Number': batch_val,
                                    'Expiration Date': override.get('expiration', '')
                                })
                        st.dataframe(pd.DataFrame(preview_rows), use_container_width=True)

                    if st.button("📤 Generate Batch Update CSV", type="primary", use_container_width=True):
                        with st.spinner("Generating batch update export..."):
                            csv_buffer, row_count = generate_distru_batch_update_csv(
                                packages, manual_overrides
                            )
                            st.success(
                                f"✅ Batch update export: {row_count} packages "
                                f"({len(matched_with_batch)} auto + {manual_ready} manual)"
                            )
                            st.download_button(
                                label="📥 Download Batch Update CSV",
                                data=csv_buffer.getvalue(),
                                file_name=f"distru_batch_update_{manifest_num}.csv",
                                mime="text/csv",
                                type="primary",
                                use_container_width=True
                            )
                else:
                    st.warning(
                        "⚠️ No packages ready for export. "
                        "Enter batch numbers manually above, then click Save."
                    )

                st.markdown("---")

                with st.expander("📦 Full Distru Export (All Fields)"):
                    st.markdown("""
                    Full export with all Distru fields:
                    Distru ID, Package Number, Product Name, License, Location, Batch, Expiration, Harvest, Description, Bins
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
        st.info("👆 Upload a transfer manifest PDF to get started")
        st.markdown(f"""
        ### How to Use

        1. **Upload Manifest**: Upload a Metrc transfer manifest PDF
        2. **Review Overview**: Check manifest info and package count
        3. **Generate Worksheet**: Click button to create printable worksheet
        4. **Download & Print**: Download PDF and print for receiving
        5. **Optional**: Upload Distru CSV for batch number export + manual entry

        ### ✨ What's New in v{VERSION}

        - ✅ **Manual Batch Entry**: Packages with missing or aggregate batches now have an editable table
        - ✅ **Merged export**: Auto-extracted and manually entered batches combined in one CSV
        - ✅ **Pre-filled expiration**: Expiration date auto-filled from Lab Testing Date when available
        - ✅ **Persistent**: Manual entries are preserved across interactions (cleared on new manifest)

        ### Batch Number Logic

        | Scenario | Batch Source | Included in Export |
        |---|---|---|
        | Valid single batch from manifest | 🤖 Auto | ✅ Always |
        | Aggregate batch (contains comma) | ✏️ Manual entry | ✅ If entered manually |
        | No Production Batch field | ✏️ Manual entry | ✅ If entered manually |
        | Not matched to Distru | N/A | ❌ Never |
        """)

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Version {VERSION}**")

    with st.sidebar.expander("📋 Changelog"):
        st.markdown("""
        **v3.9** (2026-03-04) 🆕
        - ✏️ Manual Batch Entry table for missing/aggregate packages
        - 🔀 Auto + manual batches merged in Batch Update CSV
        - 💾 Session state persists entries across interactions
        - 📅 Expiration date pre-filled from lab date when available

        **v3.8** (2025-03-04)
        - Aggregate batch cleansing (commas → blank)
        - Missing batch leaves field blank
        - Expiration unaffected in all cases

        **v3.7** (2025-01-30)
        - Removed unused tabs and debug columns
        - Cleaner Package List layout

        **v3.6** (2025-01-30)
        - NEW: Batch Update Export (Distru ID, Batch, Expiration)
        - Expiration = Lab Date + 1 year

        **v3.5** (2025-01-30) ⚠️ CRITICAL FIX
        - Package IDs: all 24 chars correctly captured

        **v3.4** (2025-12-01)
        - Distru CSV integration and METRC ID matching

        **v3.3** (2025-11-19)
        - Combined Batch/Qty/Sell-By column
        """)


if __name__ == "__main__":
    main()