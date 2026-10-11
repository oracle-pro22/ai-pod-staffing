import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const workspaceDir = 'C:\\Users\\smaikoti\\Desktop\\ai-pod-staffing';
const skillDir = 'C:\\Users\\smaikoti\\.codex\\plugins\\cache\\openai-primary-runtime\\presentations\\26.1007.11041\\skills\\presentations';
const pythonExecutable = 'C:\\Users\\smaikoti\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe';
process.env.RUNTIME_NODE_MODULES = 'C:\\Users\\smaikoti\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\node_modules';
const candidatePath = path.join(workspaceDir, '.codex-ppt-review', 'draft5.pptx');
const finalPath = path.join(workspaceDir, 'output', 'presentations', 'Maikoti_Shamish_BioSlide_AI_Pod_Staffing_v3.pptx');
const stagingDir = path.join(workspaceDir, '.codex-ppt-review');

await fs.mkdir(path.dirname(finalPath), { recursive: true });
const { finalizePresentation } = await import(pathToFileURL(path.join(skillDir, 'container_tools', 'artifact_tool_utils.mjs')).href);
const result = await finalizePresentation({
  workspaceDir,
  candidatePath,
  finalPath,
  pythonExecutable,
  integrityValidatorPath: path.join(skillDir, 'container_tools', 'inspect_presentation_package_integrity.py'),
  layoutValidatorPath: path.join(skillDir, 'container_tools', 'inspect_presentation_layout_geometry.py'),
  layoutArgs: ['--expected-slide-size-emu', '12192000,6858000', '--validate-bullet-geometry', '--validate-heading-fit'],
  explicitTotalSlideCount: 1,
  requiredNativeTableOwnerSlides: [],
  requiredNativeChartOwnerSlides: [],
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, 'bio-v3.validation.json'),
});
console.log(JSON.stringify(result, null, 2));
