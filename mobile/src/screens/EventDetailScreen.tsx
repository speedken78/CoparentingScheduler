import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { schedulesApi } from '../api/schedules';
import { useAuthStore } from '../store/auth';
import { CustodyEvent } from '../api/types';
import { Pill } from '../components/ui/Pill';
import { colors } from '../theme/colors';
import { spacing, radius } from '../theme/spacing';
import { typography } from '../theme/typography';
import { formatEventDate, formatEventTime } from '../utils/formatDate';

export const EventDetailScreen = () => {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const { eventId, caseId } = route.params as { eventId: string; caseId: string };
  const { user } = useAuthStore();
  const [event, setEvent] = useState<CustodyEvent | null>(null);

  useEffect(() => {
    loadEvent();
  }, [eventId]);

  const loadEvent = async () => {
    try {
      const e = await schedulesApi.getEvent(caseId, eventId);
      setEvent(e);
    } catch {}
  };

  if (!event) {
    return (
      <View style={styles.container}>
        <Text style={styles.loading}>載入中…</Text>
      </View>
    );
  }

  const isMe = event.custodian_id === user?.id;

  return (
    <View style={styles.container}>
      <View style={styles.topBar}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.closeBtn}>
          <Text style={styles.closeIcon}>✕</Text>
        </TouchableOpacity>
        <Text style={styles.topTitle}>排程詳情</Text>
        <View style={{ width: 36 }} />
      </View>

      <ScrollView style={styles.body}>
        <View style={styles.card}>
          <View style={styles.row}>
            <Text style={styles.dateText}>{formatEventDate(event.starts_at)}</Text>
            <Pill type={isMe ? 'me' : 'other'} />
          </View>

          <View style={styles.timeBlock}>
            <Text style={styles.timeLabel}>時間</Text>
            <Text style={styles.timeValue}>
              {formatEventTime(event.starts_at)} – {formatEventTime(event.ends_at)}
            </Text>
          </View>

          <View style={styles.divider} />

          <InfoRow label="狀態" value={statusLabel(event.status)} />
          {event.handover_location && (
            <InfoRow label="交接地點" value={event.handover_location} />
          )}
          {event.notes && (
            <InfoRow label="備註" value={event.notes} />
          )}
          {event.rule_id && (
            <InfoRow label="來源規則" value={event.rule_id} />
          )}
        </View>
      </ScrollView>
    </View>
  );
};

const InfoRow = ({ label, value }: { label: string; value: string }) => (
  <View style={infoStyles.row}>
    <Text style={infoStyles.label}>{label}</Text>
    <Text style={infoStyles.value}>{value}</Text>
  </View>
);

const infoStyles = StyleSheet.create({
  row: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: spacing.sm },
  label: { ...typography.caption, color: colors.text.tertiary },
  value: { ...typography.body, color: colors.text.primary, flex: 1, textAlign: 'right' },
});

function statusLabel(s: CustodyEvent['status']): string {
  const map: Record<string, string> = {
    scheduled: '已排程',
    confirmed: '已確認',
    in_progress: '進行中',
    completed: '已完成',
    missed: '未出現',
    disputed: '有爭議',
    cancelled: '已取消',
  };
  return map[s] ?? s;
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background.primary },
  loading: { ...typography.body, color: colors.text.tertiary, textAlign: 'center', marginTop: 80 },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.xl,
    paddingBottom: spacing.md,
    borderBottomWidth: 0.5,
    borderBottomColor: colors.border.light,
  },
  closeBtn: { width: 36, height: 36, justifyContent: 'center', alignItems: 'center' },
  closeIcon: { fontSize: 16, color: colors.text.secondary },
  topTitle: { ...typography.h3, color: colors.text.primary },
  body: { flex: 1, padding: spacing.lg },
  card: {
    backgroundColor: colors.background.card,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 0.5,
    borderColor: colors.border.light,
  },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.md },
  dateText: { ...typography.h3, color: colors.text.primary },
  timeBlock: { marginBottom: spacing.md },
  timeLabel: { ...typography.caption, color: colors.text.tertiary, marginBottom: 2 },
  timeValue: { ...typography.h2, color: colors.text.primary },
  divider: { height: 0.5, backgroundColor: colors.border.light, marginVertical: spacing.md },
});
