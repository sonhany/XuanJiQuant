import registry from '../config/llm_models.json';

type ModelOption = { id: string; label: string; note?: string };
type ProviderDefinition = {
  label: string;
  client_label: string;
  default_model: string;
  models: ModelOption[];
  aliases: Record<string, string>;
};

const providers = registry.providers as Record<string, ProviderDefinition>;

export const providerOptions = Object.entries(providers).map(([id, definition]) => ({
  id,
  label: definition.label,
}));

export function normalizeProvider(provider: unknown): string {
  const value = String(provider || '').trim().toLowerCase();
  return providers[value] ? value : registry.default_provider;
}

export function modelOptions(provider: unknown): ModelOption[] {
  return providers[normalizeProvider(provider)].models;
}

export function defaultModel(provider: unknown): string {
  return providers[normalizeProvider(provider)].default_model;
}

export function normalizeModel(provider: unknown, model: unknown): string {
  const definition = providers[normalizeProvider(provider)];
  const value = String(model || definition.default_model).trim();
  const migrated = definition.aliases?.[value] || value;
  return definition.models.some((item) => item.id === migrated) ? migrated : definition.default_model;
}

export const DEFAULT_OPENCODE_MODEL = defaultModel('opencode');

export function normalizeOpenCodeModel(model: unknown): string {
  return normalizeModel('opencode', model);
}
