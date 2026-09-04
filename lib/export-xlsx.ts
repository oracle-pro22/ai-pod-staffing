type WorkbookCell = string | number | boolean | null | undefined;

type WorkbookExport = {
  fileName: string;
  sheetName: string;
  headers: string[];
  rows: WorkbookCell[][];
};

const XLSX_MIME_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

function escapeXml(value: WorkbookCell): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function columnName(index: number): string {
  let name = '';
  let value = index + 1;
  while (value > 0) {
    const remainder = (value - 1) % 26;
    name = String.fromCharCode(65 + remainder) + name;
    value = Math.floor((value - 1) / 26);
  }
  return name;
}

function safeSheetName(value: string): string {
  return value.replace(/[\\/*?:[\]]/g, ' ').trim().slice(0, 31) || 'Sheet1';
}

function inlineStringCell(value: WorkbookCell, reference: string, styleId = 0): string {
  const style = styleId ? ` s="${styleId}"` : '';
  return `<c r="${reference}" t="inlineStr"${style}><is><t xml:space="preserve">${escapeXml(value)}</t></is></c>`;
}

export async function downloadExcelWorkbook({ fileName, sheetName, headers, rows }: WorkbookExport): Promise<void> {
  const { default: JSZip } = await import('jszip');
  const zip = new JSZip();
  const safeName = safeSheetName(sheetName);
  const allRows = [headers, ...rows];
  const finalColumn = columnName(Math.max(headers.length - 1, 0));
  const finalRow = Math.max(allRows.length, 1);
  const range = `A1:${finalColumn}${finalRow}`;
  const widths = headers.map((header, columnIndex) => {
    const contentWidth = Math.max(
      header.length,
      ...rows.map((row) => String(row[columnIndex] ?? '').length),
    );
    return Math.min(Math.max(contentWidth + 2, 12), 45);
  });
  const sheetRows = allRows.map((row, rowIndex) => {
    const cells = headers.map((_, columnIndex) => inlineStringCell(
      row[columnIndex],
      `${columnName(columnIndex)}${rowIndex + 1}`,
      rowIndex === 0 ? 1 : 0,
    )).join('');
    return `<row r="${rowIndex + 1}"${rowIndex === 0 ? ' ht="24" customHeight="1"' : ''}>${cells}</row>`;
  }).join('');

  zip.file('[Content_Types].xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>`);
  zip.folder('_rels')?.file('.rels', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`);
  zip.folder('xl')?.file('workbook.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="${escapeXml(safeName)}" sheetId="1" r:id="rId1"/></sheets>
</workbook>`);
  zip.folder('xl')?.folder('_rels')?.file('workbook.xml.rels', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`);
  zip.folder('xl')?.file('styles.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2"><font><sz val="11"/><name val="Aptos"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Aptos"/></font></fonts>
  <fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF2B6F6D"/><bgColor indexed="64"/></patternFill></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"><alignment vertical="center"/></xf></cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>`);
  zip.folder('xl')?.folder('worksheets')?.file('sheet1.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="${range}"/>
  <sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
  <sheetFormatPr defaultRowHeight="18"/>
  <cols>${widths.map((width, index) => `<col min="${index + 1}" max="${index + 1}" width="${width}" customWidth="1"/>`).join('')}</cols>
  <sheetData>${sheetRows}</sheetData>
  <autoFilter ref="${range}"/>
</worksheet>`);

  const blob = await zip.generateAsync({ type: 'blob', mimeType: XLSX_MIME_TYPE, compression: 'DEFLATE' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName.toLowerCase().endsWith('.xlsx') ? fileName : `${fileName}.xlsx`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
