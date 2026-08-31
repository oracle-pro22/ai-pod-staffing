import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "C:\\Users\\smaikoti\\Downloads\\FY27 Initiatives-CSS Programs-Key Contacts - WIP.xlsx";
const outputDir = "C:\\Users\\smaikoti\\Desktop\\ai-pod-staffing\\.codex-xlsx-review\\renders";

await fs.mkdir(outputDir, { recursive: true });
const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);

const overview = await workbook.inspect({
  kind: "workbook,sheet,table,definedName,drawing",
  maxChars: 20000,
  tableMaxRows: 8,
  tableMaxCols: 12,
  tableMaxCellChars: 120,
});
console.log("===== OVERVIEW =====");
console.log(overview.ndjson);

const sheetSummary = await workbook.inspect({
  kind: "sheet",
  include: "id,name",
  maxChars: 12000,
});
console.log("===== SHEETS =====");
console.log(sheetSummary.ndjson);

const records = sheetSummary.ndjson
  .split(/\r?\n/)
  .filter(Boolean)
  .map((line) => {
    try { return JSON.parse(line); } catch { return null; }
  })
  .filter(Boolean);

const sheetNames = [];
for (const record of records) {
  const name = record.name ?? record.sheetName ?? record.value?.name;
  if (typeof name === "string" && !sheetNames.includes(name)) sheetNames.push(name);
}

for (const sheetName of sheetNames) {
  console.log(`===== DATA: ${sheetName} =====`);
  const data = await workbook.inspect({
    kind: "region,formula,table,drawing",
    sheetId: sheetName,
    maxChars: 30000,
    tableMaxRows: 200,
    tableMaxCols: 30,
    tableMaxCellChars: 250,
    options: { maxResults: 500 },
  });
  console.log(data.ndjson);

  try {
    const safeName = sheetName.replace(/[<>:"/\\|?*]+/g, "_");
    const preview = await workbook.render({
      sheetName,
      autoCrop: "all",
      scale: 1,
      format: "png",
    });
    await fs.writeFile(path.join(outputDir, `${safeName}.png`), new Uint8Array(await preview.arrayBuffer()));
  } catch (error) {
    console.log(`RENDER_ERROR ${sheetName}: ${error?.message ?? error}`);
  }
}

const mainSheet = workbook.worksheets.getItem("FY27 CSS Initiatives");
const mainValues = mainSheet.getRange("A1:X27").values;
const dataRows = mainValues.slice(3);
let currentTechPlay = null;
let currentSalesPlay = null;
const initiatives = dataRows.map((row, index) => {
  if (row[0]) currentTechPlay = String(row[0]).trim();
  if (row[1]) currentSalesPlay = String(row[1]).trim();
  return {
    excelRow: index + 4,
    techPlay: currentTechPlay,
    salesPlay: currentSalesPlay,
    initiative: row[2] ? String(row[2]).trim() : null,
    globalCode: row[3] ? String(row[3]).trim() : null,
    regionalCode: row[4] ? String(row[4]).trim() : null,
    comments: row[5] ? String(row[5]).trim() : null,
    gtmLead: row[6] ? String(row[6]).trim() : null,
    pmLead: row[7] ? String(row[7]).trim() : null,
    regionalPocs: row.slice(8, 12).filter(Boolean).map(String),
    uptake: row.slice(12, 16).filter(Boolean).map(String),
    salesEnablement: row.slice(16, 20).filter(Boolean).map(String),
    deliveryTam: row.slice(20, 24).filter(Boolean).map(String),
  };
});

const isPending = (value) => !value || /\b(tbd|work in progress|under development|no campaign code|do we have|\?\?)\b/i.test(value);
const techPlayCounts = {};
for (const item of initiatives) techPlayCounts[item.techPlay] = (techPlayCounts[item.techPlay] ?? 0) + 1;
const metrics = {
  initiativeCount: initiatives.length,
  techPlayCounts,
  missingOrPendingGlobalCodes: initiatives.filter((x) => isPending(x.globalCode)).map((x) => ({ row: x.excelRow, initiative: x.initiative, value: x.globalCode })),
  missingGtmLeads: initiatives.filter((x) => !x.gtmLead).map((x) => ({ row: x.excelRow, initiative: x.initiative })),
  missingPmLeads: initiatives.filter((x) => !x.pmLead).map((x) => ({ row: x.excelRow, initiative: x.initiative })),
  rowsWithAnyRegionalPoc: initiatives.filter((x) => x.regionalPocs.length > 0).length,
  rowsMissingAllRegionalPocs: initiatives.filter((x) => x.regionalPocs.length === 0).map((x) => ({ row: x.excelRow, initiative: x.initiative })),
  rowsWithAnyUptake: initiatives.filter((x) => x.uptake.length > 0).length,
  rowsMissingAllUptake: initiatives.filter((x) => x.uptake.length === 0).map((x) => ({ row: x.excelRow, initiative: x.initiative })),
  uptakeValues: initiatives.flatMap((x) => x.uptake),
  rowsWithAnySalesEnablement: initiatives.filter((x) => x.salesEnablement.length > 0).length,
  rowsWithAnyDeliveryTam: initiatives.filter((x) => x.deliveryTam.length > 0).length,
  rowsWithComments: initiatives.filter((x) => x.comments).map((x) => ({ row: x.excelRow, initiative: x.initiative, comment: x.comments })),
};
console.log("===== METRICS =====");
console.log(JSON.stringify(metrics, null, 2));

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  maxChars: 12000,
  summary: "formula error scan",
});
console.log("===== FORMULA ERRORS =====");
console.log(errors.ndjson);
