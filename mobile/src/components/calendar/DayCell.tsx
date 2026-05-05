import React from 'react';
import { TouchableOpacity, Text, StyleSheet } from 'react-native';
import { colors } from '../../theme/colors';
import { typography } from '../../theme/typography';

type CellType = 'me' | 'other' | 'conflict' | 'none';

interface Props {
  date: number;
  type: CellType;
  isToday?: boolean;
  isSelected?: boolean;
  onPress: () => void;
}

export const DayCell = ({ date, type, isToday, isSelected, onPress }: Props) => (
  <TouchableOpacity
    style={[
      styles.cell,
      type === 'me' && styles.cellMe,
      type === 'other' && styles.cellOther,
      type === 'conflict' && styles.cellConflict,
      isSelected && styles.cellSelected,
    ]}
    onPress={onPress}
    activeOpacity={0.7}
  >
    <Text style={[
      styles.text,
      type === 'me' && styles.textMe,
      type === 'other' && styles.textOther,
      type === 'conflict' && styles.textConflict,
      isToday && styles.textToday,
    ]}>
      {date}
    </Text>
  </TouchableOpacity>
);

const styles = StyleSheet.create({
  cell: {
    width: 32,
    height: 32,
    borderRadius: 8,
    justifyContent: 'center',
    alignItems: 'center',
  },
  cellMe: { backgroundColor: colors.brand.primaryLight },
  cellOther: { backgroundColor: colors.counterparty.primaryLight },
  cellConflict: { backgroundColor: colors.conflict.cellBackground },
  cellSelected: { borderWidth: 2, borderColor: colors.brand.primary },
  text: { ...typography.body, color: colors.text.secondary },
  textMe: { color: colors.brand.primaryAccent, fontWeight: '500' },
  textOther: { color: colors.counterparty.primaryAccent, fontWeight: '500' },
  textConflict: { color: colors.conflict.cellText, fontWeight: '500' },
  textToday: { fontWeight: '700' },
});
