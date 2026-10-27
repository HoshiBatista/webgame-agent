export const NOTES_LIMIT = 3000;
export const TEMPLATE_TITLE_LIMIT = 50;
export const TEMPLATE_DESCRIPTION_LIMIT = 3000;

// Count Unicode code points like Python len(), including spaces and line breaks.
export const characterCount = (text: string) => Array.from(text).length;
export const appendTemplate = (draft: string, template: string) =>
  draft.trim() ? `${draft}\n\n${template}` : template;
