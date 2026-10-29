import { Vaquill } from "@vaquill-ai/sdk";
import { searchStatutesTool, getStatuteSectionTextTool } from "@vaquill-ai/ai-sdk";

const client = new Vaquill({ maxCredits: 30 });
const tools = {
  searchStatutes: searchStatutesTool(client),
  getStatuteSectionText: getStatuteSectionTextTool(client),
};
