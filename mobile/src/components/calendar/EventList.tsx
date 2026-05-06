import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Alert } from 'react-native';
import { CustodyEvent } from '../../api/types';
import { colors } from '../../theme/colors';
import { spacing, radius } from '../../theme/spacing';
import { typography } from '../../theme/typography';
import { formatEventTime } from '../../utils/formatDate';
import { Pill } from '../ui/Pill';

interface Props {
  events: CustodyEvent[];
  currentUserId: string;
  onDeleteEvent?: (eventId: string) => Promise<void>;
}

export const EventList = ({ events, currentUserId, onDeleteEvent }: Props) => {
  if (events.length === 0) {
    return <Text style={styles.empty}>這天沒有排程</Text>;
  }

  const handleLongPress = (event: CustodyEvent) => {
    if (!onDeleteEvent) return;
    Alert.alert(
      '刪除排程',
      `確定要刪除 ${formatEventTime(event.starts_at)}–${formatEventTime(event.ends_at)} 的排程嗎？`,
      [
        { text: '取消', style: 'cancel' },
        {
          text: '刪除',
          style: 'destructive',
          onPress: () => onDeleteEvent(event.id),
        },
      ],
    );
  };

  return (
    <View style={styles.container}>
      {events.map(e => {
        const isMe = e.custodian_id === currentUserId;
        return (
          <TouchableOpacity
            key={e.id}
            style={styles.row}
            onLongPress={() => handleLongPress(e)}
            activeOpacity={0.7}
          >
            <View style={[styles.stripe, isMe ? styles.stripeMe : styles.stripeOther]} />
            <View style={styles.content}>
              <Text style={styles.time}>
                {formatEventTime(e.starts_at)}–{formatEventTime(e.ends_at)}
              </Text>
              {e.notes && <Text style={styles.notes} numberOfLines={1}>{e.notes}</Text>}
            </View>
            <Pill type={isMe ? 'me' : 'other'} />
          </TouchableOpacity>
        );
      })}
      {onDeleteEvent && (
        <Text style={styles.hint}>長按排程可刪除</Text>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: { gap: spacing.xs },
  empty: { ...typography.caption, color: colors.text.tertiary, textAlign: 'center', marginTop: spacing.md },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.background.card,
    borderRadius: radius.md,
    overflow: 'hidden',
    borderWidth: 0.5,
    borderColor: colors.border.light,
    gap: spacing.sm,
    paddingRight: spacing.sm,
    paddingVertical: spacing.sm,
  },
  stripe: { width: 3, alignSelf: 'stretch' },
  stripeMe: { backgroundColor: colors.brand.primary },
  stripeOther: { backgroundColor: colors.counterparty.primary },
  content: { flex: 1, paddingLeft: spacing.sm },
  time: { ...typography.body, color: colors.text.primary },
  notes: { ...typography.caption, color: colors.text.tertiary, marginTop: 2 },
  hint: { ...typography.caption, color: colors.text.tertiary, textAlign: 'center', marginTop: spacing.xs },
});
