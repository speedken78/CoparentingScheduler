import React, { useState, useEffect } from 'react';
import { View, Text, ScrollView, StyleSheet, Alert } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { useCaseStore } from '../store/case';
import { useAuthStore } from '../store/auth';
import { schedulesApi } from '../api/schedules';
import { reportsApi } from '../api/reports';
import { CustodyEvent } from '../api/types';
import { Button } from '../components/ui/Button';
import { EventCard } from '../components/ui/EventCard';
import { EmptyState } from '../components/ui/EmptyState';
import { colors } from '../theme/colors';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';
import { format } from 'date-fns';
import { zhTW } from 'date-fns/locale';

export const RecordsScreen = () => {
  const navigation = useNavigation<any>();
  const { currentCase } = useCaseStore();
  const { user } = useAuthStore();
  const [events, setEvents] = useState<CustodyEvent[]>([]);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    if (currentCase) loadRecords();
  }, [currentCase]);

  const loadRecords = async () => {
    if (!currentCase) return;
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), 1);
    const end = new Date(now.getFullYear(), now.getMonth() + 1, 0);
    try {
      const { items } = await schedulesApi.listEvents(currentCase.id, start, end);
      setEvents(items);
    } catch {}
  };

  const handleGenerateReport = async () => {
    if (!currentCase) return;
    setGenerating(true);
    try {
      const now = new Date();
      const periodStart = new Date(now.getFullYear(), now.getMonth(), 1);
      const periodEnd = new Date(now.getFullYear(), now.getMonth() + 1, 0);

      const report = await reportsApi.create({
        case_id: currentCase.id,
        period_start: periodStart,
        period_end: periodEnd,
        report_type: 'monthly',
      });

      navigation.navigate('ReportPreview', { reportId: report.id, caseId: currentCase.id });
    } catch (e: any) {
      Alert.alert('產生失敗', e.message || '請稍後再試');
    } finally {
      setGenerating(false);
    }
  };

  const monthLabel = format(new Date(), 'M 月', { locale: zhTW });

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>接送紀錄</Text>
        <Text style={styles.headerSub}>{monthLabel} · 具法律效力</Text>
      </View>

      <ScrollView style={styles.body} showsVerticalScrollIndicator={false}>
        <Text style={styles.sectionLabel}>本月排程紀錄</Text>

        {events.length === 0 ? (
          <EmptyState icon="📋" title="本月尚無紀錄" subtitle="在 AI 助理中建立排程後會顯示在這裡" />
        ) : (
          events.map(e => (
            <EventCard
              key={e.id}
              event={e}
              currentUserId={user?.id ?? ''}
              onPress={() => navigation.navigate('EventDetail', { eventId: e.id, caseId: currentCase!.id })}
            />
          ))
        )}

        <View style={styles.generateSection}>
          <Button
            onPress={handleGenerateReport}
            variant="primary"
            loading={generating}
            disabled={!currentCase || events.length === 0}
          >
            產生本月 PDF 報告
          </Button>
          <Text style={styles.generateHint}>
            PDF 含稽核雜湊，具法律效力
          </Text>
        </View>

        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background.tertiary },
  header: {
    backgroundColor: colors.brand.primary,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.xl,
    paddingBottom: spacing.lg,
  },
  headerTitle: { ...typography.h2, color: colors.text.inverse },
  headerSub: { ...typography.caption, color: colors.text.inverse, opacity: 0.8, marginTop: 2 },
  body: { flex: 1, padding: spacing.lg },
  sectionLabel: {
    ...typography.sectionLabel,
    color: colors.text.tertiary,
    marginBottom: spacing.sm,
  },
  generateSection: { marginTop: spacing.xl, alignItems: 'center' },
  generateHint: {
    ...typography.caption,
    color: colors.text.tertiary,
    marginTop: spacing.sm,
    textAlign: 'center',
  },
});
