import streamlit as st
import fitz  # PyMuPDF
import io
import zipfile
import re
from collections import Counter

st.set_page_config(page_title="Rozdělení PDF na samostatné stránky", page_icon="📄")

st.title("Rozdělení PDF na samostatné stránky podle jména")
st.markdown("""
Nahrajte PDF, aplikace ho rozdělí na jednotlivé stránky, detekuje jméno a vygeneruje ZIP soubor ke stažení.
""")

def sanitize_filename(name, allow_spaces_in_output=False):
    name = str(name)
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = name.replace("\n", " ").replace("\r", " ")
    name = name.strip()
    if not allow_spaces_in_output:
        name = name.replace(" ", "_")
        name = re.sub(r'_+', '_', name)
    else:
        name = re.sub(r'\s+', ' ', name)
    name = name.strip('_ ')
    return name if name else "neznamy_text"

def find_name_with_regex(text_to_search):
    if not text_to_search:
        return None
    name_pattern_labeled = r"(?i)(?:Jméno a příjmení|Účastník|Student|Žák|Name and surname|Name|Přednášející|Autor)\s*:\s*([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž'-]+(?:\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž'-]+){1,2})"
    match = re.search(name_pattern_labeled, text_to_search)
    if match:
        return match.group(1).strip()
    general_name_pattern = r"\b([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž'-]+(?:\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž'-]+){1,2})\b"
    potential_names = []
    lines = text_to_search.split('\n') if '\n' in text_to_search else [text_to_search]
    for line in lines:
        matches = re.findall(general_name_pattern, line)
        for m_candidate_tuple in matches:
            m_candidate = m_candidate_tuple if isinstance(m_candidate_tuple, str) else m_candidate_tuple[0]
            words = m_candidate.split()
            if len(words) >= 2 and \
               not (m_candidate.isupper() and len(m_candidate) > 7) and \
               all(len(w) > 1 or w.istitle() or w.isupper() for w in words if not w.endswith('.')):
                potential_names.append(m_candidate.strip())
    if potential_names:
        return potential_names[0]
    return None

def extract_name_from_page(page):
    try:
        blocks = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]
    except Exception:
        plain_text = page.get_text()
        return find_name_with_regex(plain_text)
    candidate_texts_for_name = []
    all_font_sizes_on_page = []
    for block in blocks:
        if block['type'] == 0:
            for line in block['lines']:
                for span in line['spans']:
                    all_font_sizes_on_page.append(round(span['size'], 1))
    if not all_font_sizes_on_page:
        return find_name_with_regex(page.get_text())
    unique_sorted_sizes = sorted(list(set(all_font_sizes_on_page)), reverse=True)
    name_target_font_sizes = set()
    if unique_sorted_sizes:
        median_size = sorted(all_font_sizes_on_page)[len(all_font_sizes_on_page) // 2] if all_font_sizes_on_page else 10
        for s in unique_sorted_sizes:
            if s >= median_size * 0.9:
                name_target_font_sizes.add(s)
        if not name_target_font_sizes and unique_sorted_sizes:
            name_target_font_sizes = {unique_sorted_sizes[0]}
    for block in blocks:
        if block['type'] == 0:
            for line in block['lines']:
                current_line_text_parts = []
                line_has_formatting_for_name = False
                for span in line['spans']:
                    is_bold = (span['flags'] & (1 << 4)) != 0
                    is_relevant_size_for_name = round(span['size'], 1) in name_target_font_sizes
                    if is_bold or is_relevant_size_for_name:
                        line_has_formatting_for_name = True
                    current_line_text_parts.append(span['text'])
                if line_has_formatting_for_name and current_line_text_parts:
                    candidate_texts_for_name.append("".join(current_line_text_parts).strip())
    if candidate_texts_for_name:
        for text in candidate_texts_for_name:
            name = find_name_with_regex(text)
            if name:
                return name
    plain_text_page = page.get_text()
    return find_name_with_regex(plain_text_page)

def detect_document_title(doc, num_pages_to_scan=2):
    potential_titles_with_scores = []
    all_font_sizes_globally = []
    for i in range(min(num_pages_to_scan, len(doc))):
        page = doc.load_page(i)
        try:
            blocks = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]
            for block in blocks:
                if block['type'] == 0:
                    for line in block['lines']:
                        for span in line['spans']:
                            all_font_sizes_globally.append(round(span['size'], 1))
        except Exception:
            continue
    if not all_font_sizes_globally:
        if len(doc) > 0:
            first_page_text = doc.load_page(0).get_text("text")
            first_line = first_page_text.split('\n', 1)[0].strip()
            if first_line and len(first_line.split()) > 1 and len(first_line) < 100:
                return first_line
        return "Neznamy_dokument"
    font_counts = Counter(all_font_sizes_globally)
    if not font_counts: return "Neznamy_dokument"
    sorted_sizes = sorted(all_font_sizes_globally)
    median_size = sorted_sizes[len(sorted_sizes) // 2]
    title_font_threshold = max(median_size * 1.2, median_size + 1.5, 12)
    for i in range(min(num_pages_to_scan, len(doc))):
        page = doc.load_page(i)
        page_height = page.rect.height
        try:
            blocks = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]
            for block_idx, block in enumerate(blocks):
                if block['type'] == 0:
                    if block['bbox'][1] > page_height * 0.6 and i > 0:
                        continue
                    if block['bbox'][1] > page_height * 0.75 and i == 0:
                        continue
                    for line_idx, line in enumerate(block['lines']):
                        line_text_parts = [span['text'] for span in line['spans']]
                        line_text = "".join(line_text_parts).strip()
                        if not line_text or len(line_text.split()) < 2 or len(line_text.split()) > 15:
                            continue
                        avg_line_size = 0
                        span_sizes_in_line = [round(s['size'], 1) for s in line['spans']]
                        if span_sizes_in_line:
                            avg_line_size = sum(span_sizes_in_line) / len(span_sizes_in_line)
                        is_large_enough_for_title = avg_line_size >= title_font_threshold
                        if is_large_enough_for_title:
                            position_score = ((page_height - block['bbox'][1]) / page_height) * 20
                            length_score = len(line_text)
                            size_score = (avg_line_size - title_font_threshold) * 5
                            upper_penalty = 0
                            if line_text.isupper() and len(line_text.split()) > 3:
                                upper_penalty = 15
                            first_page_bonus = 0
                            if i == 0 and block_idx < 2 and line_idx < 2:
                                first_page_bonus = 25
                            if find_name_with_regex(line_text):
                                length_score /= 2
                            if re.match(r"^(OBSAH|ÚVOD|ZÁVĚR|PŘÍLOHA|STRANA \d+)$", line_text, re.IGNORECASE):
                                length_score /= 3
                            total_score = position_score + length_score + size_score + first_page_bonus - upper_penalty
                            if total_score > 0:
                                potential_titles_with_scores.append((line_text, total_score))
        except Exception:
            continue
    if potential_titles_with_scores:
        potential_titles_with_scores.sort(key=lambda x: x[1], reverse=True)
        return potential_titles_with_scores[0][0]
    else:
        if len(doc) > 0:
            page0_text = doc.load_page(0).get_text("text")
            lines0 = [line.strip() for line in page0_text.split('\n') if line.strip()]
            if lines0 and len(lines0[0].split()) > 1 and len(lines0[0]) < 100:
                return lines0[0]
        return "Neznamy_dokument"

uploaded_file = st.file_uploader("Nahrajte PDF soubor", type=["pdf"])

if uploaded_file:
    try:
        pdf_bytes = uploaded_file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        num_pages = len(doc)
        st.success(f"PDF úspěšně načteno ({num_pages} stran).")

        detected_doc_title_raw = detect_document_title(doc, num_pages_to_scan=2)
        confirmed_doc_title_raw = st.text_input(
            "Navržený název dokumentu (můžete upravit):",
            value=detected_doc_title_raw
        )

        doc_title_for_naming = sanitize_filename(confirmed_doc_title_raw.strip(), allow_spaces_in_output=True)
        if not doc_title_for_naming or doc_title_for_naming.lower() == "neznamy_dokument":
            doc_title_prefix_for_file = ""
        else:
            doc_title_prefix_for_file = f"{doc_title_for_naming} - "

        folder_name_base = sanitize_filename(confirmed_doc_title_raw.strip(), allow_spaces_in_output=False)
        if not folder_name_base or folder_name_base.lower() == "neznamy_dokument":
            folder_name_base = "rozdelene_dokumenty"
        else:
            folder_name_base = f"rozdelene_{folder_name_base}"

        if st.button("Rozdělit PDF a stáhnout ZIP soubor"):
            progress_bar = st.progress(0)
            output_zip = io.BytesIO()
            with zipfile.ZipFile(output_zip, mode="w") as zf:
                for i in range(num_pages):
                    page = doc.load_page(i)
                    person_name_raw = extract_name_from_page(page)
                    person_name_for_naming = "Nezname_jmeno"
                    if person_name_raw:
                        person_name_for_naming = sanitize_filename(person_name_raw, allow_spaces_in_output=True)
                    page_number_suffix = f"str_{i+1:03d}"
                    filename_components = []
                    if doc_title_for_naming and doc_title_for_naming.lower() != "neznamy_dokument":
                        filename_components.append(doc_title_for_naming)
                    if person_name_for_naming != "Nezname_jmeno":
                        filename_components.append(person_name_for_naming)
                    elif not filename_components:
                        filename_components.append("Nezname_jmeno")
                    if len(filename_components) == 2:
                        base_name_part = f"{filename_components[0]} - {filename_components[1]}"
                    elif len(filename_components) == 1:
                        base_name_part = filename_components[0]
                    else:
                        base_name_part = "Neznamy_soubor"
                    final_filename_raw = f"{base_name_part}_{page_number_suffix}"
                    final_filename_sanitized = sanitize_filename(final_filename_raw, allow_spaces_in_output=False)
                    pdf_filename = f"{final_filename_sanitized}.pdf"
                    single_page_doc = fitz.open()
                    single_page_doc.insert_pdf(doc, from_page=i, to_page=i)
                    pdf_bytes = single_page_doc.tobytes()
                    single_page_doc.close()
                    zf.writestr(pdf_filename, pdf_bytes)
                    # === ZDE AKTUALIZUJEME PROGRESS BAR ===
                    progress = int((i + 1) / num_pages * 100)
                    progress_bar.progress(progress)
            output_zip.seek(0)
            progress_bar.empty()
            st.success("Hotovo! ZIP soubor s rozdělenými stránkami je připraven ke stažení.")
            st.download_button(
                label="Stáhnout ZIP soubor",
                data=output_zip,
                file_name=f"{folder_name_base}.zip",
                mime="application/zip"
            )
    except Exception as e:
        st.error(f"Nastala chyba při zpracování PDF: {e}")
