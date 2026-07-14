import zipfile
import xml.etree.ElementTree as ET
import os
import sys

def docx_to_md(docx_path, md_path):
    if not os.path.exists(docx_path):
        print(f"Error: File not found: {docx_path}")
        return False

    try:
        # docx is a zip file
        with zipfile.ZipFile(docx_path) as docx:
            # Main document content is in word/document.xml
            xml_content = docx.read('word/document.xml')
            
            # Relationships for images or links (optional, if we want to extract them)
            try:
                rels_content = docx.read('word/_rels/document.xml.rels')
                rels_root = ET.fromstring(rels_content)
                namespaces_rels = {'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}
                rels = {}
                for rel in rels_root.findall('.//Relationship', namespaces=None):
                    r_id = rel.get('Id')
                    r_type = rel.get('Type')
                    r_target = rel.get('Target')
                    rels[r_id] = (r_type, r_target)
            except Exception:
                rels = {}

        root = ET.fromstring(xml_content)
        
        # XML namespaces used by Word
        ns = {
            'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
            'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
        }

        markdown_lines = []

        # Iterate through paragraphs and tables in order
        # The body is under w:body
        body = root.find('w:body', ns)
        if body is None:
            print("Could not find document body.")
            return False

        # Helper to process paragraph element
        def process_paragraph(p_elem):
            # Check paragraph properties
            pPr = p_elem.find('w:pPr', ns)
            is_heading = False
            heading_level = 0
            is_list = False
            
            if pPr is not None:
                # Check for styles (headings)
                pStyle = pPr.find('w:pStyle', ns)
                if pStyle is not None:
                    val = pStyle.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
                    if val and val.startswith('Heading'):
                        try:
                            heading_level = int(val.replace('Heading', ''))
                            is_heading = True
                        except ValueError:
                            pass
                    elif val and 'Title' in val:
                        heading_level = 1
                        is_heading = True
                    elif val and 'Subtitle' in val:
                        heading_level = 2
                        is_heading = True
                
                # Check for list items
                numPr = pPr.find('w:numPr', ns)
                if numPr is not None:
                    is_list = True

            # Process runs
            p_text = ""
            for r in p_elem.findall('w:r', ns):
                # Text content
                r_text = "".join(t.text for t in r.findall('w:t', ns) if t.text)
                
                # Check formatting
                rPr = r.find('w:rPr', ns)
                bold = False
                italic = False
                underline = False
                
                if rPr is not None:
                    # Bold can be a tag <w:b/> or <w:b w:val="true"/>
                    b = rPr.find('w:b', ns)
                    if b is not None and b.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val') != 'false':
                        bold = True
                    
                    # Italic
                    i = rPr.find('w:i', ns)
                    if i is not None and i.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val') != 'false':
                        italic = True
                
                if r_text:
                    if bold and italic:
                        r_text = f"***{r_text}***"
                    elif bold:
                        r_text = f"**{r_text}**"
                    elif italic:
                        r_text = f"*{r_text}*"
                    
                p_text += r_text

            if is_heading and p_text.strip():
                prefix = "#" * heading_level
                return f"{prefix} {p_text.strip()}"
            elif is_list and p_text.strip():
                return f"- {p_text}"
            else:
                return p_text

        # Process tables
        def process_table(tbl_elem):
            table_lines = []
            rows = tbl_elem.findall('w:tr', ns)
            if not rows:
                return ""
            
            # We want to extract cells for each row
            parsed_rows = []
            for r in rows:
                cells = r.findall('w:tc', ns)
                parsed_cells = []
                for c in cells:
                    # A cell contains paragraphs
                    cell_text = []
                    for p in c.findall('w:p', ns):
                        p_text = process_paragraph(p)
                        if p_text:
                            cell_text.append(p_text)
                    parsed_cells.append(" ".join(cell_text).replace('\n', ' ').strip())
                parsed_rows.append(parsed_cells)
            
            if not parsed_rows:
                return ""

            # Determine column widths (or just output standard Markdown table)
            num_cols = max(len(row) for row in parsed_rows)
            
            # Format row
            def format_row(row_cells):
                # Pad row to match max columns
                padded = row_cells + [""] * (num_cols - len(row_cells))
                # Clean pipe symbols to avoid breaking tables
                cleaned = [cell.replace('|', '\\|') for cell in padded]
                return "| " + " | ".join(cleaned) + " |"
            
            # Add header
            table_lines.append(format_row(parsed_rows[0]))
            # Add separator
            table_lines.append("| " + " | ".join(["---"] * num_cols) + " |")
            
            # Add data rows
            for row in parsed_rows[1:]:
                table_lines.append(format_row(row))
            
            return "\n".join(table_lines) + "\n"

        # Walk through children of body
        for child in body:
            tag = child.tag.split('}')[-1]
            if tag == 'p':
                line = process_paragraph(child)
                # Avoid inserting too many blank lines
                markdown_lines.append(line)
            elif tag == 'tbl':
                markdown_lines.append("")
                markdown_lines.append(process_table(child))
                markdown_lines.append("")
        
        # Write to file
        with open(md_path, 'w', encoding='utf-8') as f:
            # Join paragraphs with double newlines if they are not already separated
            # Let's filter out consecutive empty lines
            filtered_lines = []
            prev_empty = False
            for line in markdown_lines:
                if line is None or line.strip() == "":
                    if not prev_empty:
                        filtered_lines.append("")
                        prev_empty = True
                else:
                    filtered_lines.append(line)
                    prev_empty = False
            
            # Reconstruct with proper double spacing for paragraphs
            final_content = []
            for i, line in enumerate(filtered_lines):
                # If it's a header or list item, maybe single newline, else double
                if line.startswith('#'):
                    if i > 0 and final_content[-1] != "":
                        final_content.append("")
                    final_content.append(line)
                    final_content.append("")
                elif line.startswith('-'):
                    final_content.append(line)
                elif line == "":
                    if final_content and final_content[-1] != "":
                        final_content.append("")
                else:
                    final_content.append(line)
                    final_content.append("")
            
            f.write("\n".join(final_content))
        
        print(f"Success: Converted to {md_path}")
        return True
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error converting document: {e}")
        return False

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python docx_to_md.py <input.docx> <output.md>")
        sys.exit(1)
    
    docx_to_md(sys.argv[1], sys.argv[2])
