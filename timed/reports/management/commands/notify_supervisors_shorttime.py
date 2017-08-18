from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mass_mail
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string

from timed.employment.serializers import UserSerializer


class Command(BaseCommand):
    """
    Send notification when supervisees have shorttime in given time frame.

    Example how it works:

    We have set following options

    Today = Thursday 27/7/2017
    Days = 7
    Offset = 5
    Ratio = 0.9

    with these set shorttime would be checked between 17/7/2017 and 23/7/2017.
    A notification will be sent to supervisors if ratio between reported and
    expected worktime is lower than 90%.
    """

    help = 'Notify supervisors when supervisees have reported shortime.'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.serializer = UserSerializer()

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            default=7,
            type=int,
            dest='days',
            help='Length of period to check shorttime in'
        )
        parser.add_argument(
            '--offset',
            default=5,
            type=int,
            dest='offset',
            help='Period will end today minus given offset.'
        )
        parser.add_argument(
            '--ratio',
            default=0.9,
            type=float,
            dest='ratio',
            help=(
                'Ratio between expected and reported time '
                'before it is considered shorttime'
            )
        )

    def handle(self, *args, **options):
        days = options['days']
        offset = options['offset']
        ratio = options['ratio']

        today = date.today()
        # -1 as we also skip today
        end = today - timedelta(days=offset - 1)
        start = end - timedelta(days=days - 1)

        supervisees = self._get_supervisees_with_shorttime(start, end, ratio)
        self._notify_supervisors(start, end, ratio, supervisees)

    def _decimal_hours(self, duration):
        return duration.total_seconds() / 3600

    def _get_supervisees_with_shorttime(self, start, end, ratio):
        """
        Get supervisees which reported less hours than they should have.

        :return: dict mapping all supervisees with shorttime with tuple of
                 reported, expected, balance and actual ratio.
        """
        supervisees_shorttime = {}
        supervisees = get_user_model().objects.all_supervisees()
        for supervisee in supervisees:
            worktime = self.serializer.get_worktime(supervisee, start, end)
            reported, expected, balance = worktime
            if expected == timedelta(0):
                continue

            supervisee_ratio = reported / expected
            if supervisee_ratio < ratio:
                supervisees_shorttime[supervisee.id] = (
                    self._decimal_hours(reported),
                    self._decimal_hours(expected),
                    self._decimal_hours(balance),
                    supervisee_ratio
                )

        return supervisees_shorttime

    def _notify_supervisors(self, start, end, ratio, supervisees):
        """
        Notify supervisors about their supervisees.

        :param supervisees: dict whereas key is id of supervisee and
                            value as a worktime tuple of
                            reported, expected, balance and ratio
        """
        supervisors = get_user_model().objects.all_supervisors()
        subject = '[Timed] Report supervisees with shorttime'
        from_email = settings.DEFAULT_FROM_EMAIL
        mails = []

        for supervisor in supervisors:
            suspects = supervisor.supervisees.filter(
                id__in=supervisees.keys()).order_by('first_name')
            suspects_shorttime = [
                (suspect, supervisees[suspect.id]) for suspect in suspects
            ]
            if suspects.count() > 0 and supervisor.email:
                body = render_to_string(
                    'mail/notify_supervisor_shorttime.txt', {
                        'start': start,
                        'end': end,
                        'ratio': ratio,
                        # format:
                        # [(user, (reported, expected, balance, ratio)), ...]
                        'suspects': suspects_shorttime
                    }
                )
                mails.append((subject, body, from_email, [supervisor.email]))

        if len(mails) > 0:
            send_mass_mail(mails)