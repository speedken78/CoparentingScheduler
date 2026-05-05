import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import {
  startOfMonth, endOfMonth, eachDayOfInterval,
  getDay, format, isSameDay, isToday,
} from 'date-fns';
import { CustodyEvent } from '../../api/types';
import { colors } from '../../theme/colors';
import { spacing } from '../../theme/spacing';
import { typography } from '../../theme/typography';
import { DayCell } from './DayCell';

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

interface Props {
  month: Date;
  events: CustodyEvent[];
  currentUserId: string;
  selectedDate: string;
  onSelectDate: (date: string) => void;
}

type CellType = 'me' | 'other' | 'conflict' | 'none';

export const MonthGrid = ({ month, events, currentUserId, selectedDate, onSelectDate }: Props) => {
  const days = eachDayOfInterval({ start: startOfMonth(month), end: endOfMonth(month) });
  const startPad = getDay(days[0]);

  const getCellType = (day: Date): CellType => {
    const dateStr = format(day, 'yyyy-MM-dd');
    const dayEvents = events.filter(e => e.starts_at.startsWith(dateStr));
    if (dayEvents.length === 0) return 'none';
    const hasMe = dayEvents.some(e => e.custodian_id === currentUserId);
    const hasOther = dayEvents.some(e => e.custodian_id !== currentUserId);
    if (hasMe && hasOther) return 'conflict';
    if (hasMe) return 'me';
    return 'other';
  };

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        {WEEKDAYS.map(d => (
          <Text key={d} style={styles.weekday}>{d}</Text>
        ))}
      </View>
      <View style={styles.grid}>
        {Array.from({ length: startPad }).map((_, i) => (
          <View key={`pad-${i}`} style={styles.cellPlaceholder} />
        ))}
        {days.map(day => {
          const dateStr = format(day, 'yyyy-MM-dd');
          return (
            <DayCell
              key={dateStr}
              date={day.getDate()}
              type={getCellType(day)}
              isToday={isToday(day)}
              isSelected={selectedDate === dateStr}
              onPress={() => onSelectDate(dateStr)}
            />
          );
        })}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { paddingHorizontal: spacing.md },
  header: {
    flexDirection: 'row',
    marginBottom: spacing.xs,
  },
  weekday: {
    flex: 1,
    ...typography.captionMedium,
    color: colors.text.tertiary,
    textAlign: 'center',
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 4,
  },
  cellPlaceholder: { width: 32, height: 32 },
});
