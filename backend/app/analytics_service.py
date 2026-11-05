"""Admin analytics: KPIs, daily/hourly series and an Excel export for a date range.

Dates are calendar days in the fare policy's timezone (Asia/Kolkata by default), inclusive at
both ends. Rides are counted on the day they were requested; completions, fares and revenue on
the day the trip was completed.
"""
import base64
import io
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from sqlalchemy import select
from . import db, fare_service
from .models import FareQuote, Ride, RidePayment, RevenueLedger, RideRating, User
from .location_service import utcnow
from .services import ApiError

MAX_DAYS = 366
OUTCOMES = [('COMPLETED', 'Completed'), ('CANCELLED', 'Cancelled'), ('NO_DRIVER_FOUND', 'No driver found'), ('ACTIVE', 'Still in progress')]
ZERO = Decimal('0.00')


def timezone_name():
    return fare_service.current()[1]['timezone']


def parse_range(params):
    zone = ZoneInfo(timezone_name())
    today = utcnow().replace(tzinfo=timezone.utc).astimezone(zone).date()
    try:
        end = date.fromisoformat(params.get('to') or today.isoformat())
        start = date.fromisoformat(params.get('from') or (end - timedelta(days=29)).isoformat())
    except ValueError:
        raise ApiError('Dates must use YYYY-MM-DD')
    if start > end:
        raise ApiError('The start date must be on or before the end date')
    if (end - start).days + 1 > MAX_DAYS:
        raise ApiError(f'Choose a range of at most {MAX_DAYS} days')
    if start < date(2000, 1, 1) or end > today + timedelta(days=366):
        raise ApiError('Choose dates between 2000 and next year')
    return start, end, zone


def utc_bounds(start, end, zone):
    """Naive-UTC [lower, upper) matching how timestamps are stored."""
    edge = lambda day: datetime.combine(day, time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
    return edge(start), edge(end + timedelta(days=1))


def local(value, zone):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(zone)


def money(value):
    return str(Decimal(value or 0).quantize(Decimal('0.01')))


def load(lower, upper):
    """Rides requested in range plus rides completed in range, with fare, payment and ledger."""
    requested = select(Ride.id).where(Ride.requested_at >= lower, Ride.requested_at < upper)
    completed = select(Ride.id).where(Ride.completed_at >= lower, Ride.completed_at < upper)
    rows = db.session.execute(
        select(Ride, FareQuote, RidePayment, RevenueLedger)
        .join(FareQuote, FareQuote.id == Ride.quote_id)
        .outerjoin(RidePayment, RidePayment.ride_id == Ride.id)
        .outerjoin(RevenueLedger, RevenueLedger.ride_id == Ride.id)
        .where(Ride.id.in_(requested.union(completed)))
        .order_by(Ride.requested_at)
    ).all()
    return rows


def outcome(ride):
    return ride.status if ride.status in ('COMPLETED', 'CANCELLED', 'NO_DRIVER_FOUND') else 'ACTIVE'


def totals(rows, lower, upper):
    requested = [row for row in rows if lower <= row.Ride.requested_at < upper]
    completed = [row for row in rows if row.Ride.completed_at and lower <= row.Ride.completed_at < upper]
    gross = sum((row.FareQuote.total for row in completed), ZERO)
    return requested, completed, gross


def users_created(lower, upper):
    counts = Counter()
    # User.created_at is timezone-aware; compare in Python so every database behaves the same.
    for role, created in db.session.execute(select(User.role, User.created_at).where(User.role.in_(('rider', 'driver')))):
        stamp = created.replace(tzinfo=None) if created.tzinfo is None else created.astimezone(timezone.utc).replace(tzinfo=None)
        if lower <= stamp < upper:
            counts[role] += 1
    return counts


def delta(current, previous):
    if not previous:
        return None
    return round((float(current) - float(previous)) / float(previous) * 100, 1)


def summary(params):
    start, end, zone = parse_range(params)
    lower, upper = utc_bounds(start, end, zone)
    days = (end - start).days + 1
    previous_lower, previous_upper = utc_bounds(start - timedelta(days=days), start - timedelta(days=1), zone)
    rows = load(previous_lower, upper)
    requested, completed, gross = totals(rows, lower, upper)
    previous_requested, previous_completed, previous_gross = totals(rows, previous_lower, previous_upper)

    company = sum((row.RevenueLedger.company_amount for row in completed if row.RevenueLedger), ZERO)
    driver = sum((row.RevenueLedger.driver_amount for row in completed if row.RevenueLedger), ZERO)
    cancelled = sum(1 for row in requested if row.Ride.status == 'CANCELLED')
    surged = sum(1 for row in completed if row.FareQuote.surge_multiplier > 1)
    ratings = db.session.scalars(select(RideRating.stars).where(RideRating.rater_role == 'rider', RideRating.created_at >= lower, RideRating.created_at < upper)).all()
    joined = users_created(lower, upper)

    daily = {start + timedelta(days=offset): dict(requested=0, completed=0, cancelled=0, gross_fares=ZERO, company_revenue=ZERO) for offset in range(days)}
    for row in requested:
        bucket = daily.get(local(row.Ride.requested_at, zone).date())
        if bucket:
            bucket['requested'] += 1
            bucket['cancelled'] += row.Ride.status == 'CANCELLED'
    for row in completed:
        bucket = daily.get(local(row.Ride.completed_at, zone).date())
        if bucket:
            bucket['completed'] += 1
            bucket['gross_fares'] += row.FareQuote.total
            bucket['company_revenue'] += row.RevenueLedger.company_amount if row.RevenueLedger else ZERO

    hourly = [0] * 24
    for row in requested:
        hourly[local(row.Ride.requested_at, zone).hour] += 1

    outcomes = Counter(outcome(row.Ride) for row in requested)
    payments = Counter()
    for row in completed:
        paid = row.RidePayment and row.RidePayment.status == 'CONFIRMED'
        payments[(row.RidePayment.method if paid else None) or 'PENDING'] += 1

    return dict(
        range=dict(start=start.isoformat(), end=end.isoformat(), days=days, timezone=zone.key),
        kpis=dict(
            requested_rides=len(requested), requested_change_pct=delta(len(requested), len(previous_requested)),
            completed_rides=len(completed), completed_change_pct=delta(len(completed), len(previous_completed)),
            gross_fares=money(gross), gross_fares_change_pct=delta(gross, previous_gross),
            company_revenue=money(company), driver_earnings=money(driver),
            average_fare=money(gross / len(completed)) if completed else None,
            cancellation_rate_pct=round(cancelled / len(requested) * 100, 1) if requested else None,
            surge_share_pct=round(surged / len(completed) * 100, 1) if completed else None,
            average_driver_rating=round(sum(ratings) / len(ratings), 2) if ratings else None, ratings=len(ratings),
            new_riders=joined['rider'], new_drivers=joined['driver'],
        ),
        daily=[dict(date=day.isoformat(), requested=value['requested'], completed=value['completed'], cancelled=value['cancelled'], gross_fares=money(value['gross_fares']), company_revenue=money(value['company_revenue'])) for day, value in daily.items()],
        hourly=[dict(hour=hour, requests=count) for hour, count in enumerate(hourly)],
        outcomes=[dict(key=key, label=label, rides=outcomes.get(key, 0)) for key, label in OUTCOMES],
        payments=[dict(key=key, label=label, rides=payments.get(key, 0)) for key, label in (('CASH', 'Cash'), ('ONLINE', 'Online'), ('PENDING', 'Not yet paid'))],
    )


def export(params):
    """Excel workbook for the range, returned as base64 inside JSON so it travels encrypted."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    data = summary(params)
    start, end, zone = parse_range(params)
    lower, upper = utc_bounds(start, end, zone)
    rows = [row for row in load(lower, upper) if lower <= row.Ride.requested_at < upper]
    people = {user.id: user for user in db.session.scalars(select(User).where(User.id.in_({row.Ride.rider_id for row in rows} | {row.Ride.driver_id for row in rows if row.Ride.driver_id})))}
    naive = lambda value: local(value, zone).replace(tzinfo=None) if value else None
    rupees, stamp = '"₹"#,##0.00', 'yyyy-mm-dd hh:mm'
    header_font, header_fill = Font(bold=True, color='FFFFFF'), PatternFill('solid', fgColor='243C23')

    book = Workbook()
    def sheet(title, headers, records, formats=None, first=False):
        ws = book.active if first else book.create_sheet()
        ws.title = title
        ws.append(headers)
        for cell in ws[1]:
            cell.font, cell.fill, cell.alignment = header_font, header_fill, Alignment(vertical='center')
        for record in records:
            ws.append(record)
        for index, header in enumerate(headers, start=1):
            letter = get_column_letter(index)
            fmt = (formats or {}).get(header)
            if fmt:
                for cell in ws[letter][1:]:
                    cell.number_format = fmt
            longest = max([len(str(header))] + [len(str(cell.value)) for cell in ws[letter][1:200] if cell.value is not None])
            ws.column_dimensions[letter].width = min(max(longest + 2, 10), 48)
        ws.freeze_panes = 'A2'
        return ws

    k = data['kpis']
    pct = lambda value: None if value is None else value / 100
    summary_rows = [
        ('Report range', f"{data['range']['start']} to {data['range']['end']} ({data['range']['days']} days)", None),
        ('Timezone', data['range']['timezone'], None),
        ('Generated', naive(utcnow()), stamp),
        ('Rides requested', k['requested_rides'], None),
        ('Rides completed', k['completed_rides'], None),
        ('Gross fares', Decimal(k['gross_fares']), rupees),
        ('Company revenue', Decimal(k['company_revenue']), rupees),
        ('Driver earnings', Decimal(k['driver_earnings']), rupees),
        ('Average fare', Decimal(k['average_fare']) if k['average_fare'] else None, rupees),
        ('Cancellation rate', pct(k['cancellation_rate_pct']), '0.0%'),
        ('Completed rides with surge', pct(k['surge_share_pct']), '0.0%'),
        ('Average driver rating (from riders)', k['average_driver_rating'], '0.00'),
        ('Ratings received', k['ratings'], None),
        ('New riders', k['new_riders'], None),
        ('New drivers', k['new_drivers'], None),
    ]
    ws = sheet('Summary', ['Metric', 'Value'], [(label, value) for label, value, _ in summary_rows], first=True)
    for offset, (_, _, fmt) in enumerate(summary_rows, start=2):
        if fmt:
            ws.cell(offset, 2).number_format = fmt
        ws.cell(offset, 2).alignment = Alignment(horizontal='left')
    ws.column_dimensions['B'].width = 34

    sheet('Daily', ['Date', 'Rides requested', 'Rides completed', 'Rides cancelled', 'Gross fares', 'Company revenue'],
          [(date.fromisoformat(day['date']), day['requested'], day['completed'], day['cancelled'], Decimal(day['gross_fares']), Decimal(day['company_revenue'])) for day in data['daily']],
          {'Date': 'yyyy-mm-dd', 'Gross fares': rupees, 'Company revenue': rupees})

    who = lambda user_id: f'{people[user_id].name} ({people[user_id].user_code})' if user_id in people else ''
    sheet('Rides', ['Ride ID', 'Requested at', 'Status', 'Rider', 'Driver', 'Pickup', 'Destination', 'Distance (km)', 'Fare', 'Surge multiplier', 'Surge reason', 'Payment method', 'Payment status', 'Completed at', 'Cancelled at', 'Cancellation reason', 'Company amount', 'Driver amount'],
          [(row.Ride.id, naive(row.Ride.requested_at), row.Ride.status.replace('_', ' ').title(), who(row.Ride.rider_id), who(row.Ride.driver_id), row.FareQuote.pickup, row.FareQuote.destination,
            row.FareQuote.distance_km, row.FareQuote.total, row.FareQuote.surge_multiplier, row.FareQuote.surge_reason,
            (row.RidePayment.method or '').title() if row.RidePayment else '', (row.RidePayment.status or '').title() if row.RidePayment else '',
            naive(row.Ride.completed_at), naive(row.Ride.cancelled_at), row.Ride.cancellation_reason or '',
            row.RevenueLedger.company_amount if row.RevenueLedger else None, row.RevenueLedger.driver_amount if row.RevenueLedger else None) for row in rows],
          {'Requested at': stamp, 'Completed at': stamp, 'Cancelled at': stamp, 'Distance (km)': '0.00', 'Fare': rupees, 'Surge multiplier': '0.00"×"', 'Company amount': rupees, 'Driver amount': rupees})

    sheet('Hourly demand', ['Hour', 'Rides requested'], [(f"{item['hour']:02d}:00–{item['hour']:02d}:59", item['requests']) for item in data['hourly']])

    buffer = io.BytesIO()
    book.save(buffer)
    return dict(filename=f"ridez-report-{data['range']['start']}-to-{data['range']['end']}.xlsx",
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                content_base64=base64.b64encode(buffer.getvalue()).decode(), rides=len(rows))


HISTORY_DEFAULT_DAYS = 90


def history_export(user, params):
    """Ride history workbook for one user's rides (rider/driver) or every ride (admin).

    Riders never receive the driver/company split; drivers receive their own share and earnings,
    exactly as their trip history screen shows them; admins receive the full split.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    if not params.get('from'):
        params = {**params, 'from': (parse_range({'to': params.get('to')})[1] - timedelta(days=HISTORY_DEFAULT_DAYS - 1)).isoformat()}
    start, end, zone = parse_range(params)
    lower, upper = utc_bounds(start, end, zone)
    query = (select(Ride, FareQuote, RidePayment, RevenueLedger)
             .join(FareQuote, FareQuote.id == Ride.quote_id)
             .outerjoin(RidePayment, RidePayment.ride_id == Ride.id)
             .outerjoin(RevenueLedger, RevenueLedger.ride_id == Ride.id)
             .where(Ride.requested_at >= lower, Ride.requested_at < upper)
             .order_by(Ride.requested_at.desc()))
    if user.role == 'rider':
        query = query.where(Ride.rider_id == user.id)
    elif user.role == 'driver':
        query = query.where(Ride.driver_id == user.id)
    rows = db.session.execute(query).all()
    ids = {row.Ride.rider_id for row in rows} | {row.Ride.driver_id for row in rows if row.Ride.driver_id}
    people = {person.id: person for person in db.session.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    who = lambda user_id: f'{people[user_id].name} ({people[user_id].user_code})' if user_id in people else ''
    naive = lambda value: local(value, zone).replace(tzinfo=None) if value else None
    rupees, stamp = '"₹"#,##0.00', 'yyyy-mm-dd hh:mm'

    columns = [('Requested at', stamp), ('Status', None)]
    if user.role != 'rider':
        columns.append(('Rider', None))
    if user.role != 'driver':
        columns.append(('Driver', None))
    columns += [('Vehicle', None), ('Pickup', None), ('Destination', None), ('Distance (km)', '0.00'), ('Duration (min)', None),
                ('Fare', rupees), ('Surge multiplier', '0.00"×"'), ('Payment method', None), ('Payment status', None),
                ('Completed at', stamp), ('Cancelled at', stamp), ('Cancellation reason', None)]
    if user.role == 'driver':
        columns += [('Your share', '0.00"%"'), ('Your earnings', rupees)]
    if user.role == 'admin':
        columns += [('Driver amount', rupees), ('Company amount', rupees)]
    columns.append(('Ride ID', None))

    def record(row):
        ride, quote, payment, ledger = row
        values = {
            'Requested at': naive(ride.requested_at), 'Status': ride.status.replace('_', ' ').title(),
            'Rider': who(ride.rider_id), 'Driver': who(ride.driver_id),
            'Vehicle': ' · '.join(part for part in (ride.vehicle_registration, ride.vehicle_model, ride.vehicle_color) if part),
            'Pickup': quote.pickup, 'Destination': quote.destination, 'Distance (km)': quote.distance_km, 'Duration (min)': quote.duration_min,
            'Fare': quote.total, 'Surge multiplier': quote.surge_multiplier,
            'Payment method': (payment.method or '').title() if payment else '', 'Payment status': (payment.status or '').title() if payment else '',
            'Completed at': naive(ride.completed_at), 'Cancelled at': naive(ride.cancelled_at), 'Cancellation reason': ride.cancellation_reason or '',
            'Your share': ledger.driver_pct if ledger else None, 'Your earnings': ledger.driver_amount if ledger else None,
            'Driver amount': ledger.driver_amount if ledger else None, 'Company amount': ledger.company_amount if ledger else None,
            'Ride ID': ride.id,
        }
        return [values[name] for name, _ in columns]

    book = Workbook()
    ws = book.active
    ws.title = 'Ride history'
    ws.append([name for name, _ in columns])
    for cell in ws[1]:
        cell.font, cell.fill, cell.alignment = Font(bold=True, color='FFFFFF'), PatternFill('solid', fgColor='243C23'), Alignment(vertical='center')
    for row in rows:
        ws.append(record(row))
    for index, (name, fmt) in enumerate(columns, start=1):
        letter = get_column_letter(index)
        for cell in ws[letter][1:]:
            if fmt:
                cell.number_format = fmt
        longest = max([len(name)] + [len(str(cell.value)) for cell in ws[letter][1:200] if cell.value is not None])
        ws.column_dimensions[letter].width = min(max(longest + 2, 10), 48)
    ws.freeze_panes = 'A2'
    total_row = len(rows) + 3
    if rows:
        completed = [row for row in rows if row.Ride.status == 'COMPLETED']
        ws.cell(total_row, 1, f'{len(rows)} rides · {len(completed)} completed · {start.isoformat()} to {end.isoformat()} ({zone.key})').font = Font(italic=True, color='68735F')
        label = ws.cell(total_row + 1, 1, 'Completed fares total')
        label.font = Font(bold=True)
        total = ws.cell(total_row + 1, [name for name, _ in columns].index('Fare') + 1, sum((row.FareQuote.total for row in completed), ZERO))
        total.number_format, total.font = rupees, Font(bold=True)
    else:
        ws.cell(total_row, 1, f'No rides between {start.isoformat()} and {end.isoformat()}.').font = Font(italic=True, color='68735F')

    buffer = io.BytesIO()
    book.save(buffer)
    return dict(filename=f'ridez-ride-history-{start.isoformat()}-to-{end.isoformat()}.xlsx',
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                content_base64=base64.b64encode(buffer.getvalue()).decode(), rides=len(rows), start=start.isoformat(), end=end.isoformat())
