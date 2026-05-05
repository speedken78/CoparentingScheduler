import { apiClient } from './client';
import { Report, CreateReportRequest } from './types';
import { toApiDate } from '../utils/formatDate';

export const reportsApi = {
  async create(params: {
    case_id: string;
    period_start: Date;
    period_end: Date;
    report_type: CreateReportRequest['report_type'];
  }): Promise<Report> {
    const body: CreateReportRequest = {
      period_start: toApiDate(params.period_start),
      period_end: toApiDate(params.period_end),
      report_type: params.report_type,
    };
    const { data } = await apiClient.post<Report>(
      `/cases/${params.case_id}/reports/`,
      body,
    );
    return data;
  },

  async list(caseId: string): Promise<Report[]> {
    const { data } = await apiClient.get<Report[]>(`/cases/${caseId}/reports/`);
    return data;
  },

  async getDownloadUrl(caseId: string, reportId: string): Promise<string> {
    return `${process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1'}/cases/${caseId}/reports/${reportId}/download`;
  },
};
