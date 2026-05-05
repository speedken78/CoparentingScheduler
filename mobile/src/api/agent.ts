import { apiClient } from './client';
import { AgentMessageResponse } from './types';

export const agentApi = {
  async sendMessage(params: {
    case_id: string;
    text: string;
    session_id?: string;
  }): Promise<AgentMessageResponse> {
    const { data } = await apiClient.post<AgentMessageResponse>('/agent/message', params);
    return data;
  },
};
