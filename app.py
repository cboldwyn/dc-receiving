"""
DC Receiving v1.0
Extract data from Metrc transfer manifest PDFs and generate receiving worksheets

CHANGELOG:
v1.0 (2025-11-19)
- Initial release
- Extract header and package information from Metrc PDFs
- Generate receiving worksheet PDFs
- Support for multiple packages per manifest
"""

import streamlit as st
import pandas as pd
import io
import re
from datetime import datetime
import pdfplumber
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# ============================================================================
# CONFIGURATION
# ============================================================================

# Page config
st.set_page_config(
    page_title="DC Receiving v1.0",
    page_icon="📦",
    layout="wide"
)

# Version
VERSION = "1.0"

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def clean_item_name(item_name):
    """
    Clean item name by removing everything after the first comma
    
    Example:
        "Bloom Vape - 1.0g Blue Dream (BDR), CAPNA, INC. (Vape Cartridge...)"
        becomes "Bloom Vape - 1.0g Blue Dream (BDR)"
    """
    if pd.isna(item_name):
        return ""
    
    # Split on comma and take first part
    parts = str(item_name).split(',')
    return parts[0].strip()

# ============================================================================
# PDF EXTRACTION FUNCTIONS
# ============================================================================

def extract_manifest_data(pdf_file):
    """
    Extract data from Metrc transfer manifest PDF
    
    Returns:
        tuple: (header_info dict, packages list, raw_text)
    """
    header_info = {}
    packages = []
    raw_text = ""
    
    try:
        with pdfplumber.open(pdf_file) as pdf:
            # Extract text from all pages
            all_text = ""
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    all_text += page_text + "\n"
            
            raw_text = all_text
            
            # Extract header information
            header_info = extract_header_info(all_text)
            
            # Extract package information
            packages = extract_packages(all_text)
            
    except Exception as e:
        st.error(f"Error extracting PDF data: {str(e)}")
        return None, None, None
    
    return header_info, packages, raw_text

def extract_header_info(text):
    """Extract header information from manifest text"""
    header = {}
    
    # Manifest number
    manifest_match = re.search(r'Manifest No\.\s+(\d+)', text)
    if manifest_match:
        header['Manifest_Number'] = manifest_match.group(1)
    
    # Date created
    date_match = re.search(r'Date Created\s+(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s+[AP]M)', text)
    if date_match:
        header['Date_Created'] = date_match.group(1)
    
    # Originating Entity
    orig_match = re.search(r'Originating Entity\s+([^\n]+)', text)
    if orig_match:
        header['Originating_Entity'] = orig_match.group(1).strip()
    
    # Originating License Number
    orig_lic_match = re.search(r'Originating License Number\s+([^\n]+)', text)
    if orig_lic_match:
        header['Originating_License'] = orig_lic_match.group(1).strip()
    
    # Destination
    dest_match = re.search(r'1\. Destination\s+([^\n]+)', text)
    if dest_match:
        header['Destination'] = dest_match.group(1).strip()
    
    # Destination License
    dest_lic_match = re.search(r'Destination License Number\s+([^\n]+)', text)
    if dest_lic_match:
        header['Destination_License'] = dest_lic_match.group(1).strip()
    
    return header

def extract_packages(text):
    """
    Extract package information from manifest text
    
    Returns:
        list: List of package dictionaries
    """
    packages = []
    
    # Split text into sections by package number pattern
    # Pattern looks for: "1. Package | Shipped", "2. Package | Shipped", etc.
    package_sections = re.split(r'(\d+)\. Package \| Shipped', text)
    
    # First element is before any packages, skip it
    # Then pairs of (number, section_text)
    for i in range(1, len(package_sections), 2):
        if i + 1 < len(package_sections):
            package_num = package_sections[i]
            section_text = package_sections[i + 1]
            
            package_data = extract_package_details(package_num, section_text)
            if package_data:
                packages.append(package_data)
    
    return packages

def extract_package_details(package_num, section_text):
    """Extract details from a single package section"""
    package = {
        'Package_Number': package_num
    }
    
    # Package ID (the 1A... number)
    # Look for pattern like 1A4060300048D3D004765304
    package_id_match = re.search(r'(1A[A-Z0-9]{20,})', section_text)
    if package_id_match:
        package['Package_ID'] = package_id_match.group(1)
    
    # Item Name (appears after "Item Name" header and before quantity)
    # Extract text between "Item Name" and "Quantity"
    item_match = re.search(r'Item Name\s+Quantity\s*\n([^\n]+)', section_text, re.MULTILINE)
    if item_match:
        raw_item = item_match.group(1).strip()
        
        # Remove Package ID prefix if present
        if package.get('Package_ID'):
            raw_item = raw_item.replace(package['Package_ID'], '').strip()
        
        # Remove "Shp: XX ea" suffix if present
        raw_item = re.sub(r'\s*Shp:\s*\d+\s*ea\s*$', '', raw_item)
        
        # Clean the item name
        package['Item_Name_Raw'] = raw_item
        package['Item_Name'] = clean_item_name(raw_item)
    else:
        # Alternative pattern - sometimes the layout is different
        item_match2 = re.search(r'Item Name\s*\n([^\n]+)\n', section_text, re.MULTILINE)
        if item_match2:
            raw_item = item_match2.group(1).strip()
            
            # Remove Package ID prefix if present
            if package.get('Package_ID'):
                raw_item = raw_item.replace(package['Package_ID'], '').strip()
            
            # Remove "Shp: XX ea" suffix if present
            raw_item = re.sub(r'\s*Shp:\s*\d+\s*ea\s*$', '', raw_item)
            
            package['Item_Name_Raw'] = raw_item
            package['Item_Name'] = clean_item_name(raw_item)
    
    # Quantity (look for "Shp: XX ea" pattern)
    qty_match = re.search(r'Shp:\s*(\d+)\s*ea', section_text)
    if qty_match:
        package['Quantity'] = qty_match.group(1)
    
    # Item Details (look for "Wgt: X g" or similar)
    details_match = re.search(r'Item Details\s+([^\n]+)', section_text)
    if details_match:
        package['Item_Details'] = details_match.group(1).strip()
    
    # Source Production Batch
    batch_match = re.search(r'Source Production Batch\s+([^\n]+)', section_text)
    if batch_match:
        package['Batch'] = batch_match.group(1).strip()
    
    return package

# ============================================================================
# PDF GENERATION FUNCTIONS
# ============================================================================

def generate_receiving_worksheet(header_info, packages):
    """
    Generate a receiving worksheet PDF
    
    Returns:
        BytesIO buffer containing the PDF
    """
    buffer = io.BytesIO()
    
    # Create document
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
        fontSize=16,
        textColor=colors.HexColor('#008B8B'),
        spaceAfter=12,
        alignment=TA_CENTER
    )
    
    header_style = ParagraphStyle(
        'CustomHeader',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=6
    )
    
    # Story (content)
    story = []
    
    # Title
    title = Paragraph("RECEIVING WORKSHEET", title_style)
    story.append(title)
    story.append(Spacer(1, 0.2*inch))
    
    # Header Information
    if header_info:
        header_data = [
            ['Manifest #:', header_info.get('Manifest_Number', 'N/A')],
            ['Date:', header_info.get('Date_Created', 'N/A')],
            ['From:', header_info.get('Originating_Entity', 'N/A')],
            ['License:', header_info.get('Originating_License', 'N/A')],
            ['Destination:', header_info.get('Destination', 'N/A')],
        ]
        
        header_table = Table(header_data, colWidths=[1.5*inch, 5*inch])
        header_table.setStyle(TableStyle([
            ('FONT', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONT', (1, 0), (1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        
        story.append(header_table)
        story.append(Spacer(1, 0.3*inch))
    
    # Package Table
    if packages:
        # Table header
        table_data = [[
            '#',
            'Item Name',
            'Quantity\n(Verify)',
            'Batch\n(Verify)',
            'Package ID'
        ]]
        
        # Add each package
        for pkg in packages:
            row = [
                pkg.get('Package_Number', ''),
                pkg.get('Item_Name', ''),
                pkg.get('Quantity', '') + ' ea',
                pkg.get('Batch', ''),
                pkg.get('Package_ID', '')[-8:]  # Last 8 chars for space
            ]
            table_data.append(row)
        
        # Create table
        package_table = Table(
            table_data,
            colWidths=[0.4*inch, 2.8*inch, 0.9*inch, 1.5*inch, 1*inch],
            repeatRows=1  # Repeat header on each page
        )
        
        # Table style
        package_table.setStyle(TableStyle([
            # Header row
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#008B8B')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
            
            # Data rows
            ('FONT', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # Package number centered
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),     # Item name left
            ('ALIGN', (2, 1), (-1, -1), 'CENTER'),  # Rest centered
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            
            # Borders
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#008B8B')),
            
            # Padding
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            
            # Alternating row colors
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F0F0F0')]),
        ]))
        
        story.append(package_table)
        story.append(Spacer(1, 0.3*inch))
    
    # Footer notes
    notes = Paragraph(
        "<b>Notes:</b> Verify quantities and batch numbers match the physical products. "
        "Make any corrections directly on this worksheet.",
        styles['Normal']
    )
    story.append(notes)
    story.append(Spacer(1, 0.2*inch))
    
    # Signature line
    sig_data = [
        ['Received By:', '_' * 40, 'Date:', '_' * 20],
    ]
    sig_table = Table(sig_data, colWidths=[1*inch, 3*inch, 0.7*inch, 2*inch])
    sig_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(sig_table)
    
    # Build PDF
    doc.build(story)
    
    buffer.seek(0)
    return buffer

# ============================================================================
# MAIN APPLICATION
# ============================================================================

def main():
    st.title(f"📦 DC Receiving v{VERSION}")
    st.markdown("Extract data from Metrc transfer manifest PDFs and generate receiving worksheets")
    
    # Sidebar
    st.sidebar.header("📄 Upload Manifest")
    uploaded_file = st.sidebar.file_uploader(
        "Upload Metrc PDF:",
        type=['pdf'],
        help="Upload a Metrc Cannabis Transportation Manifest PDF"
    )
    
    st.sidebar.markdown("---")
    
    # Main content
    if uploaded_file is None:
        st.info("👆 Upload a Metrc transfer manifest PDF to get started")
        
        # Instructions
        st.markdown("### How to Use")
        st.markdown("""
        1. **Upload** a Metrc transfer manifest PDF using the sidebar
        2. **Review** the extracted information in the Data tab
        3. **Generate** a receiving worksheet PDF for verification
        4. **Download** the worksheet and use it during receiving
        
        The worksheet will list all items in the same order as the original manifest,
        making it easy to verify quantities and batch numbers and note any corrections.
        """)
        
    else:
        # Extract data from PDF
        with st.spinner("📄 Extracting data from PDF..."):
            header_info, packages, raw_text = extract_manifest_data(uploaded_file)
        
        if header_info is None or packages is None:
            st.error("❌ Failed to extract data from PDF")
            return
        
        st.success(f"✅ Extracted {len(packages)} package(s) from manifest")
        
        # Display extracted data in tabs
        tab1, tab2, tab3 = st.tabs(["📊 Overview", "📦 Packages", "🔧 Debug"])
        
        with tab1:
            st.subheader("📋 Manifest Information")
            
            if header_info:
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("**Manifest Details:**")
                    st.write(f"• Manifest #: {header_info.get('Manifest_Number', 'N/A')}")
                    st.write(f"• Date: {header_info.get('Date_Created', 'N/A')}")
                
                with col2:
                    st.markdown("**From/To:**")
                    st.write(f"• From: {header_info.get('Originating_Entity', 'N/A')}")
                    st.write(f"• To: {header_info.get('Destination', 'N/A')}")
            
            st.markdown("---")
            
            # Summary metrics
            st.subheader("📊 Summary")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Total Packages", len(packages))
            
            with col2:
                total_qty = sum(int(pkg.get('Quantity', 0)) for pkg in packages if pkg.get('Quantity', '').isdigit())
                st.metric("Total Units", f"{total_qty:,}")
            
            with col3:
                unique_items = len(set(pkg.get('Item_Name', '') for pkg in packages))
                st.metric("Unique Items", unique_items)
            
            st.markdown("---")
            
            # Generate worksheet button
            st.subheader("📄 Generate Receiving Worksheet")
            
            if st.button("🚀 Generate Worksheet PDF", type="primary"):
                with st.spinner("📄 Generating worksheet..."):
                    pdf_buffer = generate_receiving_worksheet(header_info, packages)
                
                if pdf_buffer:
                    st.success("✅ Worksheet generated successfully!")
                    
                    # Download button
                    manifest_num = header_info.get('Manifest_Number', 'unknown')
                    filename = f"receiving_worksheet_{manifest_num}.pdf"
                    
                    st.download_button(
                        label="📥 Download Worksheet",
                        data=pdf_buffer,
                        file_name=filename,
                        mime="application/pdf"
                    )
        
        with tab2:
            st.subheader("📦 Package Details")
            
            if packages:
                # Convert to DataFrame for display
                display_df = pd.DataFrame(packages)
                
                # Select columns to display
                display_cols = ['Package_Number', 'Item_Name', 'Quantity', 'Batch', 'Package_ID', 'Item_Details']
                display_cols = [col for col in display_cols if col in display_df.columns]
                
                st.dataframe(
                    display_df[display_cols],
                    use_container_width=True,
                    hide_index=True
                )
                
                # Download raw data
                st.markdown("---")
                csv_buffer = io.StringIO()
                display_df.to_csv(csv_buffer, index=False)
                
                st.download_button(
                    label="📥 Download Package Data (CSV)",
                    data=csv_buffer.getvalue(),
                    file_name=f"manifest_{header_info.get('Manifest_Number', 'unknown')}_data.csv",
                    mime="text/csv"
                )
            else:
                st.warning("No packages found in manifest")
        
        with tab3:
            st.subheader("🔧 Debug Information")
            
            st.markdown("**Extraction Summary:**")
            st.write(f"• Packages found: {len(packages)}")
            st.write(f"• Header fields: {len(header_info)}")
            
            st.markdown("---")
            
            with st.expander("📋 Header Info (Dict)"):
                st.json(header_info)
            
            with st.expander("📦 Packages (List)"):
                st.json(packages)
            
            with st.expander("📄 Raw PDF Text"):
                st.text_area("Raw Text", raw_text, height=400)
    
    # Changelog in sidebar
    with st.sidebar.expander("📋 Version History & Changelog"):
        st.markdown("""
        **v1.0** (Current)
        - Initial release
        - Extract header information from Metrc PDFs
        - Extract package details (item, quantity, batch, package ID)
        - Clean item names by removing supplier info
        - Generate receiving worksheet PDFs
        - Maintain package order from original manifest
        - Include verification columns for quantity and batch
        - Support for multiple packages per manifest
        """)
    
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Version {VERSION}**")

if __name__ == "__main__":
    main()