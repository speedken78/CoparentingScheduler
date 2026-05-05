export type RootStackParamList = {
  Login: undefined;
  Main: undefined;
  Onboarding: undefined;
  EventDetail: { eventId: string };
  ReportPreview: { reportId: string; caseId: string };
};

export type MainTabParamList = {
  Home: undefined;
  Chat: undefined;
  Calendar: undefined;
  Records: undefined;
};
