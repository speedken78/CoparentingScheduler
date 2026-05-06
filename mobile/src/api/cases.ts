import { apiClient } from './client';
import { Case, Child, CreateCaseRequest } from './types';

export const casesApi = {
  async list(): Promise<Case[]> {
    const { data } = await apiClient.get<Case[]>('/cases/');
    return data;
  },

  async create(body: CreateCaseRequest): Promise<Case> {
    const { data } = await apiClient.post<Case>('/cases/', body);
    return data;
  },

  async get(caseId: string): Promise<Case> {
    const { data } = await apiClient.get<Case>(`/cases/${caseId}/`);
    return data;
  },

  async listChildren(caseId: string): Promise<Child[]> {
    const { data } = await apiClient.get<Child[]>(`/cases/${caseId}/children/`);
    return data;
  },
};
