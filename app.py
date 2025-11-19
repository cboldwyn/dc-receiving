"""
DC Receiving Tool v2.2
Extract and process transfer manifest data from Metrc PDFs

CHANGELOG:
v2.2 (2025-11-19)
- Changed to only show Quantity Shipped (ignore any received quantities from PDF)
- Edit mode now for entering received quantities, not showing existing
- Removed Qty Received column from initial view
- Variance calculation based on newly entered received quantities

v2.1 (2025-11-19)
- Fixed item name extraction to correctly capture product names
- Added line-by-line parsing for better accuracy
- Improved handling of quantities split across lines

v2.0 (2025-11-18)
- Initial version with PDF extraction
"""

import streamlit as st
import pandas as pd
import io
import re
from typing import List, Dict, Optional

# ============================================================================
# CONFIGURATION
# ============================================================================

st.set_page_config(
    page_title="DC Receiving Tool v2.2",
    page_icon="📦",
    layout="wide"
)

VERSION = "2.2"

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

def extract_packages(text: str) -> List[Dict]:
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
                
                package_data = extract_single_package(lines, i, package_count)
                if package_data:
                    packages.append(package_data)
        
        i += 1
    
    return packages

def extract_single_package(lines: List[str], start_idx: int, package_num: int) -> Optional[Dict]:
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
    
    # Skip any short numeric-only lines
    while i < len(lines) and lines[i].strip() and lines[i].strip().isdigit() and len(lines[i].strip()) < 3:
        i += 1
    
    # Collect package ID parts
    package_id_parts = []
    while i < len(lines):
        line = lines[i].strip()
        if 'Lab Test' in line:
            break
        if line and (line[0].isalpha() or line.isdigit()) and len(line) <= 15:
            package_id_parts.append(line)
        i += 1
    
    package_data['package_id'] = ''.join(package_id_parts)
    
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
    
    package_data['item_name'] = ' '.join(item_name_parts)
    
    # Extract shipped quantity only (ignore any received quantity)
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
    
    return package_data

# ============================================================================
# DATA PROCESSING FUNCTIONS
# ============================================================================

def packages_to_dataframe(packages: List[Dict]) -> pd.DataFrame:
    """Convert package list to DataFrame - only show shipped quantities"""
    if not packages:
        return pd.DataFrame()
    
    rows = []
    for pkg in packages:
        row = {
            'Package #': pkg['package_number'],
            'Package ID': pkg['package_id'],
            'Item Name': pkg['item_name'],
            'Qty Shipped': pkg['quantity_shipped'],
            'Production Batch': pkg['production_batch'],
            'Weight': pkg['item_details'].get('weight', ''),
            'Volume': pkg['item_details'].get('volume', ''),
            'Strain': pkg['item_details'].get('strain', '')
        }
        rows.append(row)
    
    return pd.DataFrame(rows)

# ============================================================================
# MAIN APPLICATION
# ============================================================================

def main():
    st.title(f"📦 DC Receiving Tool v{VERSION}")
    st.markdown("Process transfer manifests and track received inventory")
    
    # Sidebar
    st.sidebar.header("📄 Upload Manifest")
    uploaded_file = st.sidebar.file_uploader(
        "Upload Transfer Manifest PDF:",
        type=['pdf'],
        help="Upload a Metrc transfer manifest PDF"
    )
    
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
        
        # Display manifest info
        st.subheader("📋 Manifest Information")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Manifest Number", manifest_num or "Not Found")
        with col2:
            st.metric("Destination", destination or "Not Found")
        
        # Extract packages
        with st.spinner("Extracting package data..."):
            packages = extract_packages(pdf_text)
        
        if not packages:
            st.warning("No packages found in manifest")
            
            with st.expander("🔍 Debug: View Raw Text"):
                st.text_area("PDF Text (first 2000 chars)", pdf_text[:2000], height=400)
            return
        
        st.success(f"✅ Found {len(packages)} packages")
        
        # Convert to DataFrame
        df = packages_to_dataframe(packages)
        
        # Tabs for different views
        tabs = st.tabs(["📊 Package List", "✏️ Enter Received Quantities", "📈 Summary", "🔍 Debug"])
        
        with tabs[0]:  # Package List
            st.subheader("Package List - Shipped Quantities")
            st.dataframe(df, use_container_width=True, height=600)
            
            # Download button
            csv = df.to_csv(index=False)
            st.download_button(
                "📥 Download CSV",
                csv,
                f"manifest_{manifest_num}_packages.csv",
                "text/csv",
                key="download_main"
            )
        
        with tabs[1]:  # Enter Received Quantities
            st.subheader("Enter Received Quantities")
            st.markdown("Enter the quantities you received for each package:")
            
            # Create form for receiving
            received_data = df.copy()
            received_data['Qty Received'] = 0.0
            
            for idx, row in received_data.iterrows():
                col1, col2, col3, col4 = st.columns([1, 3, 1, 1])
                
                with col1:
                    st.text(f"#{row['Package #']}")
                
                with col2:
                    # Show full item name in expander if too long
                    if len(row['Item Name']) > 50:
                        st.text(row['Item Name'][:50] + "...")
                        with st.expander("Show full name"):
                            st.text(row['Item Name'])
                    else:
                        st.text(row['Item Name'])
                
                with col3:
                    st.text(f"Shipped: {row['Qty Shipped']}")
                
                with col4:
                    received = st.number_input(
                        "Received",
                        value=float(row['Qty Shipped'] or 0),  # Default to shipped qty
                        min_value=0.0,
                        step=1.0,
                        key=f"rcv_{idx}",
                        label_visibility="collapsed"
                    )
                    received_data.at[idx, 'Qty Received'] = received
            
            # Calculate variance
            received_data['Variance'] = received_data['Qty Received'] - received_data['Qty Shipped']
            received_data['Variance %'] = received_data.apply(
                lambda row: (row['Variance'] / row['Qty Shipped'] * 100) 
                if pd.notna(row['Qty Shipped']) and row['Qty Shipped'] > 0 
                else None,
                axis=1
            )
            
            st.markdown("---")
            st.subheader("Receiving Summary")
            
            # Show variance summary
            total_shipped = received_data['Qty Shipped'].sum()
            total_received = received_data['Qty Received'].sum()
            total_variance = total_received - total_shipped
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Shipped", f"{total_shipped:,.0f} ea")
            with col2:
                st.metric("Total Received", f"{total_received:,.0f} ea")
            with col3:
                st.metric("Total Variance", f"{total_variance:,.0f} ea")
            
            # Show updated data
            st.dataframe(
                received_data[['Package #', 'Package ID', 'Item Name', 'Qty Shipped', 'Qty Received', 'Variance', 'Variance %']],
                use_container_width=True
            )
            
            # Download button
            received_csv = received_data.to_csv(index=False)
            st.download_button(
                "📥 Download Receiving Report",
                received_csv,
                f"manifest_{manifest_num}_receiving_report.csv",
                "text/csv",
                key="download_received"
            )
        
        with tabs[2]:  # Summary
            st.subheader("📈 Manifest Summary")
            
            total_packages = len(df)
            total_shipped = df['Qty Shipped'].sum() if 'Qty Shipped' in df.columns else 0
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Packages", f"{total_packages:,}")
            with col2:
                st.metric("Total Quantity Shipped", f"{total_shipped:,.0f} ea")
            
            # Show breakdown by category if we can infer it
            st.markdown("### Package Details")
            st.dataframe(
                df[['Package #', 'Item Name', 'Qty Shipped', 'Production Batch']],
                use_container_width=True
            )
        
        with tabs[3]:  # Debug
            st.subheader("🔍 Debug Information")
            
            # Show first 3 packages raw data
            st.markdown("**First 3 Packages Raw Data:**")
            for i, pkg in enumerate(packages[:3]):
                with st.expander(f"Package {i+1}: {pkg['item_name'][:50]}..."):
                    st.json(pkg)
            
            # Show DataFrame info
            st.markdown("**DataFrame Info:**")
            st.write(f"Shape: {df.shape}")
            st.write(f"Columns: {list(df.columns)}")
            
            # Show extraction stats
            st.markdown("**Extraction Statistics:**")
            stats = {
                'Total Packages': len(packages),
                'With Package ID': sum(1 for p in packages if p['package_id']),
                'With Item Name': sum(1 for p in packages if p['item_name']),
                'With Qty Shipped': sum(1 for p in packages if p['quantity_shipped'] is not None),
                'With Prod Batch': sum(1 for p in packages if p['production_batch'])
            }
            st.json(stats)
    
    else:
        # Instructions
        st.info("👆 Upload a transfer manifest PDF to get started")
        
        st.markdown("""
        ### How to Use
        
        1. **Upload Manifest**: Upload a Metrc transfer manifest PDF (before or after receiving)
        2. **Review Packages**: Check the extracted package list with shipped quantities
        3. **Enter Received Quantities**: Use the second tab to enter what you actually received
        4. **View Summary**: Check totals and variances
        5. **Download Report**: Export the receiving report as CSV
        
        ### ✨ What's New in v2.2
        
        - ✅ **Only shows shipped quantities** - Ignores any received quantities from PDF
        - ✅ **Clean receiving workflow** - Enter received quantities fresh
        - ✅ **Works with both manifest types** - Before or after receiving
        - ✅ **Variance tracking** - Automatically calculates differences
        
        ### Features
        
        - ✅ Automatic extraction from Metrc PDF manifests
        - ✅ Correct item name extraction
        - ✅ Handles multi-line text formatting
        - ✅ Works with "Accepted" and "Shipped" packages
        - ✅ Extracts weight, volume, and strain information
        - ✅ Edit mode for receiving
        - ✅ Variance calculations
        - ✅ Export to CSV
        """)
    
    # Version info in sidebar
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Version {VERSION}**")
    
    with st.sidebar.expander("📋 Changelog"):
        st.markdown("""
        **v2.2** (2025-11-19)
        - Only shows Quantity Shipped
        - Removed Qty Received from PDF
        - Clean receiving workflow
        - Works with both manifest types
        
        **v2.1** (2025-11-19)
        - Fixed item name extraction
        - Line-by-line PDF parsing
        - Better quantity handling
        
        **v2.0** (2025-11-18)
        - Initial PDF extraction version
        """)

if __name__ == "__main__":
    main()