# DC Receiving Tool v3.0

Streamlit app for processing Metrc cannabis transfer manifest PDFs and generating professional receiving worksheets.

## 🎯 Primary Function

**Generate Receiving Worksheets** - Extract package data from Metrc PDFs and create professional, printable worksheets for use during physical receiving operations.

## ✨ Features

### Core Functionality
- **PDF Extraction**: Automatically extracts manifest header and package details from Metrc PDFs
- **Worksheet Generation**: Creates professional receiving worksheets with Haven Distribution branding
- **Clean Item Names**: Removes supplier information and formatting for cleaner display
- **Verification Columns**: Built-in lines for verifying batch numbers and quantities
- **Original Order Preservation**: Maintains package order from manifest for easy cross-reference

### Additional Features
- **Digital Receiving**: Optional workflow to track received quantities and calculate variances
- **Data Export**: Export package lists and receiving reports as CSV
- **Multi-Package Support**: Handles manifests with any number of packages
- **Debug Tools**: Built-in troubleshooting for PDF extraction issues

## 📋 What It Extracts

### Manifest Header
- Manifest Number
- Originating Entity (supplier)
- Destination (receiving location)

### Package Details (for each item)
- Package Number (1, 2, 3, etc.)
- Package ID (1A... tracking number)
- Item Name (cleaned and formatted)
- Quantity Shipped
- Production Batch Number
- Item Details (weight, volume, strain)

## 🚀 Installation

### Requirements
- Python 3.8+
- pip (Python package manager)

### Setup Steps

1. **Clone or download this repository**

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Run the app:**
```bash
streamlit run app.py
```

4. **Access in browser:** http://localhost:8501

## 📖 Usage Guide

### Workflow 1: Generate Receiving Worksheet (Primary)

1. **Upload PDF**
   - Use sidebar file uploader
   - Select Metrc transfer manifest PDF

2. **Verify Extraction**
   - Check manifest information (number, origin, destination)
   - Review package count
   - Browse Package List tab to verify all items extracted correctly

3. **Generate Worksheet**
   - Click the large "Generate Receiving Worksheet PDF" button
   - Wait for generation to complete
   - Click "Download Worksheet PDF" button

4. **Print and Use**
   - Print the downloaded worksheet
   - Use during physical receiving to:
     - Verify quantities match
     - Verify batch numbers match
     - Check off items as received
     - Note any discrepancies

### Workflow 2: Digital Receiving Tracking (Optional)

1. **Upload PDF** (same as above)

2. **Navigate to "Enter Received Quantities" tab**

3. **Enter Actual Quantities**
   - For each package, enter the quantity actually received
   - Defaults to shipped quantity for convenience

4. **Review Variances**
   - Check summary metrics (Total Shipped, Total Received, Total Variance)
   - Review detailed variance table
   - Download receiving report as CSV

## 📄 Worksheet Format

The generated receiving worksheet includes:

### Header Section
- **Company Name**: HAVEN DISTRIBUTION
- **Title**: Receiving Worksheet
- **Manifest Info**: Manifest # and From (origin) on single line

### Package Table
Columns:
- **#**: Package number (1, 2, 3, etc.)
- **Item Name**: Product name with Package ID (last 8 digits) below in small font
- **Batch**: Production batch number with verification line (`_______`)
- **Quantity**: Quantity shipped with verification line (`_______`)
- **Sell-By**: Empty column for date entry

### Features
- Alternating row colors for easy reading
- Grid lines for clear separation
- Professional Haven Distribution branding (teal header)
- Compact format - fits many packages per page

## 🛠 Troubleshooting

### PDF Extraction Issues

**Problem**: "No packages found in manifest"

**Solutions**:
1. Check Debug tab → View Raw Text to verify PDF contains searchable text
2. If text is garbled or missing, PDF may be scanned image - needs OCR
3. Verify it's a standard Metrc transfer manifest format

**Problem**: Item names look wrong or incomplete

**Check**:
1. View Package List tab
2. Look at full item names
3. Most common cause: PDF formatting puts item details before name
4. Solution: Already handled in v3.0 extraction logic

**Problem**: Missing batch numbers

**Check**:
1. Verify batch numbers appear in original PDF
2. Check Package List tab to see what was extracted
3. Look for "Source Production Batch" in PDF text

### PDF Generation Issues

**Problem**: "Error generating PDF"

**Solutions**:
1. Verify at least one package was successfully extracted
2. Check that manifest number and origin were found
3. Look at error details in expander for specific issue
4. Try re-uploading the PDF

**Problem**: Worksheet doesn't match expectations

**Check**:
1. Review Package List tab to see extracted data
2. Verify data extraction is correct before generating worksheet
3. Check that all required fields are present (Item Name, Quantity, etc.)

## 📁 Project Structure

```
dc-receiving/
├── app.py                 # Main Streamlit application
├── requirements.txt       # Python dependencies
└── README.md             # This file
```

## 🔄 Version History

### v3.0 (2025-11-19) - Current
- **Restored PDF worksheet generation** (primary feature)
- Kept improved item name extraction from v2.x
- Professional worksheet layout with Haven branding
- Verification columns for batch and quantity
- Clean, compact format

### v2.2 (2025-11-19)
- Changed to only show Quantity Shipped (ignore received from PDF)
- Edit mode for entering received quantities
- Variance tracking and reporting

### v2.1 (2025-11-19)
- Fixed item name extraction for correct product names
- Line-by-line PDF parsing for better accuracy
- Improved handling of quantities split across lines

### v2.0 (2025-11-18)
- Initial version with PDF extraction
- Basic data display in tables

### v1.0 (2025-11-18)
- Original implementation with worksheet generation
- Basic extraction logic

## 🎯 Design Principles

Following Haven's Streamlit Design Guide:

1. **Version Management**: Semantic versioning (MAJOR.MINOR.PATCH)
2. **UI/UX Patterns**: Sidebar for uploads, tabs for organization, prominent action buttons
3. **Code Organization**: Clear section headers, documented functions
4. **Data Processing**: Progress indicators, error handling, validation
5. **Professional Output**: Haven branding, clean layouts, production-ready

## 📝 Dependencies

- **streamlit**: Web application framework
- **pandas**: Data manipulation and analysis
- **PyPDF2**: PDF text extraction
- **reportlab**: PDF generation and styling

All dependencies are specified in `requirements.txt` with minimum versions.

## 🚀 Deployment

### Local Development
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run app
streamlit run app.py
```

### Streamlit Cloud Deployment

1. **Push to GitHub**
   - Create repository
   - Push app.py, requirements.txt, README.md

2. **Deploy on Streamlit Cloud**
   - Go to share.streamlit.io
   - Connect GitHub account
   - Select repository and branch
   - Set main file path: `app.py`
   - Deploy

3. **Access**
   - Your app will be at: `https://[username]-[repo]-[hash].streamlit.app`

## 💡 Tips & Best Practices

1. **Always review extracted data** before generating worksheet
2. **Print worksheets immediately** upon receiving driver notification
3. **Keep original PDF** - worksheet is supplement, not replacement
4. **Use Package List tab** to export data for record-keeping
5. **Test with sample PDFs** before production use
6. **Check Debug tab** when troubleshooting extraction issues

## 🆘 Support

If you encounter issues:

1. Check the **Debug tab** in the app for technical details
2. Review this README for troubleshooting steps
3. Verify your PDF is a standard Metrc transfer manifest
4. Check that Python and all dependencies are properly installed

## 📄 License

Internal Haven Distribution tool. Not for external distribution.

---

**Version 3.0** | Last Updated: November 19, 2025