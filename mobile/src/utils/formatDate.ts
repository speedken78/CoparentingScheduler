import { format, isToday, isTomorrow, parseISO } from 'date-fns';
import { zhTW } from 'date-fns/locale';

export function formatEventDate(isoString: string): string {
  const date = parseISO(isoString);
  if (isToday(date)) return '今天';
  if (isTomorrow(date)) return '明天';
  return format(date, 'M/d（EEE）', { locale: zhTW });
}

export function formatEventTime(isoString: string): string {
  return format(parseISO(isoString), 'HH:mm');
}

export function formatMonthYear(date: Date): string {
  return format(date, 'yyyy 年 M 月', { locale: zhTW });
}

export function toApiDate(date: Date): string {
  return format(date, 'yyyy-MM-dd');
}
