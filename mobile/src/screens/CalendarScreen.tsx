import React, { useState, useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Calendar, DateData } from 'react-native-calendars';
import { useCaseStore } from '../store/case';
import { useAuthStore } from '../store/auth';
import { schedulesApi } from '../api/schedules';
import { CustodyEvent } from '../api/types';
import { EventList } from '../components/calendar/EventList';
import { colors } from '../theme/colors';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';
import { format, addMonths, subMonths } from 'date-fns';
import { zhTW } from 'date-fns/locale';

export const CalendarScreen = () => {
  const insets = useSafeAreaInsets();
  const { currentCase } = useCaseStore();
  const { user } = useAuthStore();
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [events, setEvents] = useState<CustodyEvent[]>([]);
  const [selectedDate, setSelectedDate] = useState('');
  const [markedDates, setMarkedDates] = useState<Record<string, any>>({});
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (currentCase) loadMonth(currentMonth);
  }, [currentCase, currentMonth]);

  const loadMonth = async (month: Date) => {
    if (!currentCase) return;
    const start = new Date(month.getFullYear(), month.getMonth(), 1);
    const end = new Date(month.getFullYear(), month.getMonth() + 1, 0);
    setIsLoading(true);
    try {
      const { items } = await schedulesApi.listEvents(currentCase.id, start, end);
      setEvents(items);
      buildMarked(items);
    } catch {} finally {
      setIsLoading(false);
    }
  };

  const buildMarked = (items: CustodyEvent[]) => {
    const marked: Record<string, any> = {};
    items.forEach(event => {
      const dateKey = event.starts_at.slice(0, 10);
      const isMine = event.custodian_id === user?.id;
      const existing = marked[dateKey];
      const hasOtherType = existing && existing._type !== (isMine ? 'me' : 'other');
      const cellType = hasOtherType ? 'conflict' : (isMine ? 'me' : 'other');

      marked[dateKey] = {
        _type: cellType,
        customStyles: {
          container: {
            backgroundColor: cellType === 'me'
              ? colors.brand.primaryLight
              : cellType === 'other'
              ? colors.counterparty.primaryLight
              : colors.conflict.cellBackground,
            borderRadius: 8,
          },
          text: {
            color: cellType === 'me'
              ? colors.brand.primaryAccent
              : cellType === 'other'
              ? colors.counterparty.primaryAccent
              : colors.conflict.cellText,
            fontWeight: '500',
          },
        },
      };
    });
    setMarkedDates(marked);
  };

  const handleDayPress = (day: DateData) => {
    setSelectedDate(day.dateString);
  };

  const eventsOnDate = events.filter(e => e.starts_at.startsWith(selectedDate));

  return (
    <View style={styles.container}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.sm }]}>
        <TouchableOpacity onPress={() => setCurrentMonth(m => subMonths(m, 1))}>
          <Text style={styles.arrow}>‹</Text>
        </TouchableOpacity>
        <Text style={styles.monthTitle}>
          {format(currentMonth, 'yyyy年 M月', { locale: zhTW })}
        </Text>
        <View style={styles.headerRight}>
          <TouchableOpacity onPress={() => setCurrentMonth(m => addMonths(m, 1))}>
            <Text style={styles.arrow}>›</Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={() => loadMonth(currentMonth)}
            disabled={isLoading}
            style={styles.refreshBtn}
          >
            {isLoading
              ? <ActivityIndicator size="small" color={colors.text.inverse} />
              : <Text style={styles.refreshIcon}>↻</Text>
            }
          </TouchableOpacity>
        </View>
      </View>

      <Calendar
        key={format(currentMonth, 'yyyy-MM')}
        current={format(currentMonth, 'yyyy-MM-dd')}
        markingType="custom"
        markedDates={markedDates}
        onDayPress={handleDayPress}
        hideArrows
        hideDayNames={false}
        renderHeader={() => null}
        theme={{
          calendarBackground: colors.background.primary,
          textSectionTitleColor: colors.text.tertiary,
          dayTextColor: colors.text.primary,
          todayTextColor: colors.brand.primary,
          selectedDayBackgroundColor: colors.brand.primary,
        }}
      />

      <View style={styles.legend}>
        <LegendItem color={colors.brand.primaryLight} label="我監護" />
        <LegendItem color={colors.counterparty.primaryLight} label="對方監護" />
        <LegendItem color={colors.conflict.cellBackground} label="需確認" />
      </View>

      {selectedDate ? (
        <View style={styles.eventSection}>
          <Text style={styles.eventSectionTitle}>{selectedDate} 的排程</Text>
          <EventList events={eventsOnDate} currentUserId={user?.id ?? ''} />
        </View>
      ) : (
        <View style={styles.eventSection}>
          <Text style={styles.eventSectionTitle}>點選日期查看排程</Text>
        </View>
      )}
    </View>
  );
};

const LegendItem = ({ color, label }: { color: string; label: string }) => (
  <View style={legendStyles.item}>
    <View style={[legendStyles.dot, { backgroundColor: color }]} />
    <Text style={legendStyles.text}>{label}</Text>
  </View>
);

const legendStyles = StyleSheet.create({
  item: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  dot: { width: 10, height: 10, borderRadius: 3 },
  text: { ...typography.caption, color: colors.text.secondary },
});

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background.primary },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.sm,
    backgroundColor: colors.brand.primary,
  },
  arrow: { fontSize: 24, color: colors.text.inverse, paddingHorizontal: spacing.md },
  headerRight: { flexDirection: 'row', alignItems: 'center' },
  refreshBtn: { paddingHorizontal: spacing.sm },
  refreshIcon: { fontSize: 20, color: colors.text.inverse },
  monthTitle: { ...typography.h2, color: colors.text.inverse },
  legend: {
    flexDirection: 'row',
    gap: spacing.md,
    padding: spacing.md,
    borderTopWidth: 0.5,
    borderTopColor: colors.border.light,
  },
  eventSection: { flex: 1, padding: spacing.md },
  eventSectionTitle: {
    ...typography.captionMedium,
    color: colors.text.tertiary,
    marginBottom: spacing.sm,
  },
});
