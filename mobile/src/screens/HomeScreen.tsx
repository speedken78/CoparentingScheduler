import React, { useEffect, useState } from 'react';
import { View, Text, ScrollView, StyleSheet, TouchableOpacity } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { useCaseStore } from '../store/case';
import { useAuthStore } from '../store/auth';
import { schedulesApi } from '../api/schedules';
import { casesApi } from '../api/cases';
import { CustodyEvent } from '../api/types';
import { StatCard } from '../components/ui/StatCard';
import { EventCard } from '../components/ui/EventCard';
import { EmptyState } from '../components/ui/EmptyState';
import { colors } from '../theme/colors';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';
import { formatMonthYear } from '../utils/formatDate';

export const HomeScreen = () => {
  const navigation = useNavigation<any>();
  const insets = useSafeAreaInsets();
  const { currentCase, setCurrentCase, setCases } = useCaseStore();
  const { user } = useAuthStore();
  const [events, setEvents] = useState<CustodyEvent[]>([]);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    loadCases();
  }, []);

  useEffect(() => {
    if (currentCase) loadEvents();
  }, [currentCase]);

  const loadCases = async () => {
    setLoadError(false);
    try {
      const list = await casesApi.list();
      setCases(list);
      if (list.length > 0 && !currentCase) {
        setCurrentCase(list[0]);
      } else if (list.length === 0) {
        navigation.getParent()?.navigate('Onboarding');
      }
    } catch {
      setLoadError(true);
    }
  };

  const loadEvents = async () => {
    if (!currentCase) return;
    try {
      const now = new Date();
      const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      const end = new Date(start);
      end.setDate(end.getDate() + 14);
      const { items } = await schedulesApi.listEvents(currentCase.id, start, end);
      setEvents(items);
    } catch {}
  };

  const myEvents = events.filter(e => e.custodian_id === user?.id);
  const upcomingEvents = events.slice(0, 5);

  if (loadError) {
    return <EmptyState icon="⚠" title="載入失敗" subtitle="請檢查網路連線後重新開啟 App" />;
  }

  if (!currentCase) {
    return <EmptyState title="載入中…" />;
  }

  return (
    <View style={styles.container}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.md }]}>
        <Text style={styles.headerTitle}>{currentCase.case_name}</Text>
        <Text style={styles.headerSubtitle}>
          {currentCase.custody_type === 'joint' ? '共同監護' : '單獨監護'} · {formatMonthYear(new Date())}
        </Text>
      </View>

      <ScrollView style={styles.body} showsVerticalScrollIndicator={false}>
        <View style={styles.statsRow}>
          <StatCard
            label="本期我的天數"
            value={String(myEvents.length)}
            sub={`共 ${events.length} 筆排程`}
          />
          <StatCard
            label="接下來"
            value={upcomingEvents.length > 0 ? '有排程' : '暫無'}
            sub="未來 14 天"
            valueSize="small"
          />
        </View>

        <Text style={styles.sectionLabel}>即將到來</Text>
        {upcomingEvents.length === 0 ? (
          <EmptyState icon="📅" title="暫無排程" subtitle="可在 AI 助理中建立" />
        ) : (
          upcomingEvents.map(e => (
            <EventCard
              key={e.id}
              event={e}
              currentUserId={user?.id ?? ''}
              onPress={() => navigation.navigate('EventDetail', { eventId: e.id, caseId: currentCase.id })}
            />
          ))
        )}

        <View style={{ height: 100 }} />
      </ScrollView>

      <TouchableOpacity
        style={styles.fab}
        onPress={() => navigation.navigate('Chat')}
        activeOpacity={0.85}
      >
        <Text style={styles.fabIcon}>✦</Text>
      </TouchableOpacity>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background.tertiary },
  header: {
    backgroundColor: colors.brand.primary,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.lg,
  },
  headerTitle: { ...typography.h2, color: colors.text.inverse, marginBottom: 2 },
  headerSubtitle: { ...typography.body, color: colors.text.inverse, opacity: 0.82 },
  body: { flex: 1, padding: spacing.lg },
  statsRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  sectionLabel: {
    ...typography.sectionLabel,
    color: colors.text.tertiary,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  fab: {
    position: 'absolute',
    bottom: 80,
    right: 16,
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: colors.brand.primary,
    justifyContent: 'center',
    alignItems: 'center',
    shadowColor: colors.brand.primary,
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.28,
    shadowRadius: 8,
    elevation: 4,
  },
  fabIcon: { fontSize: 22, color: colors.text.inverse },
});
