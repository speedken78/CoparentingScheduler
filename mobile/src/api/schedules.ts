import { apiClient } from './client';
import { CustodyEvent, CustodyRule } from './types';
import { toApiDate } from '../utils/formatDate';

export const schedulesApi = {
  async listEvents(
    caseId: string,
    start: Date,
    end: Date,
  ): Promise<{ items: CustodyEvent[] }> {
    const { data } = await apiClient.get<{ items: CustodyEvent[] }>(
      `/cases/${caseId}/events/`,
      { params: { start: toApiDate(start), end: toApiDate(end) } },
    );
    return data;
  },

  async listRules(caseId: string): Promise<{ items: CustodyRule[] }> {
    const { data } = await apiClient.get<{ items: CustodyRule[] }>(
      `/cases/${caseId}/rules/`,
    );
    return data;
  },

  async getEvent(caseId: string, eventId: string): Promise<CustodyEvent> {
    const { data } = await apiClient.get<CustodyEvent>(
      `/cases/${caseId}/events/${eventId}/`,
    );
    return data;
  },

  async deleteEvent(caseId: string, eventId: string): Promise<void> {
    await apiClient.delete(`/cases/${caseId}/events/${eventId}/`);
  },
};
