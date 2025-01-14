
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.db.models import Q
from edc_base.utils import age, get_utcnow
from edc_constants.constants import YES
from edc_form_validators import FormValidator
from .form_validator_mixin import ChildFormValidatorMixin


class VaccinesReceivedFormValidator(ChildFormValidatorMixin, FormValidator):

    caregiver_child_consent = 'flourish_caregiver.caregiverchildconsent'

    vaccines_received = 'flourish_child.vaccinesreceived'

    @property
    def caregiver_child_consent_cls(self):
        return django_apps.get_model(self.caregiver_child_consent)

    @property
    def vaccines_received_cls(self):
        return django_apps.get_model(self.vaccines_received)

    def clean(self):
        self.subject_identifier = self.cleaned_data.get(
            'child_immunization_history').subject_identifier
        cleaned_data = self.cleaned_data

        self.validate_consent_version_obj(self.subject_identifier)
        self.validate_vaccine_received(cleaned_data)
        self.validate_received_vaccine_fields(cleaned_data)
        self.validate_hpv_vaccine(cleaned_data)
        self.validate_dates(cleaned_data)
        dates = ['first_dose_dt', 'second_dose_dt', 'third_dose_dt', 'booster_dose_dt']
        self.check_missing_date(cleaned_data, dates=dates)
        self.validate_prev_immunization_received(cleaned_data)
        super().clean()

    @property
    def caregiver_child_consent_model(self):
        caregiver_consent = self.latest_consent_obj(self.subject_identifier)
        try:
            child_consent = caregiver_consent.caregiverchildconsent_set.filter(
                subject_identifier=self.subject_identifier).latest('consent_datetime')
        except self.caregiver_child_consent_cls.DoesNotExist:
            return None
        else:
            return child_consent

    def validate_vaccine_received(self, cleaned_data=None):
        vaccines_received = cleaned_data.get('child_immunization_history').vaccines_received
        if vaccines_received:
            self.required_if_true(
                (vaccines_received == YES),
                field_required='received_vaccine_name',
                required_msg=('You mentioned that vaccines were received. Please '
                              'indicate which ones on the table.'))

    def validate_received_vaccine_fields(self, cleaned_data=None):
        received_vaccine_name = cleaned_data.get('received_vaccine_name')
        first_dose_dt = cleaned_data.get('first_dose_dt')
        second_dose_dt = cleaned_data.get('second_dose_dt')
        third_dose_dt = cleaned_data.get('third_dose_dt')
        booster_dose_dt = cleaned_data.get('booster_dose_dt')
        if received_vaccine_name:
            if not (first_dose_dt or second_dose_dt or third_dose_dt or
                    booster_dose_dt):
                message = {'received_vaccine_name':
                           f'You provided a vaccine name {received_vaccine_name}.'
                           'Please provide details on the doses.'}
                self._errors.update(message)
                raise ValidationError(message)
        else:
            if first_dose_dt or second_dose_dt or third_dose_dt or booster_dose_dt:
                message = {'received_vaccine_name':
                           'Please provide the vaccine name before providing '
                           'details on the doses.'}
                self._errors.update(message)
                raise ValidationError(message)

    def validate_hpv_vaccine(self, cleaned_data):
        received_vaccine_name = cleaned_data.get('received_vaccine_name')
        if self.caregiver_child_consent_model:
            child_dob = self.caregiver_child_consent_model.child_dob
            child_age = age(child_dob, get_utcnow().date()).years
            if child_age < 9 and received_vaccine_name == 'hpv_vaccine':
                message = {'received_vaccine_name':
                           'Child age is less than 9, cannot select HPV vaccine'}
                self._errors.update(message)
                raise ValidationError(message)

    def validate_dates(self, cleaned_data):
        first_dose_dt = cleaned_data.get('first_dose_dt')
        second_dose_dt = cleaned_data.get('second_dose_dt')
        third_dose_dt = cleaned_data.get('third_dose_dt')
        booster_dose_dt = cleaned_data.get('booster_dose_dt')
        dates = [first_dose_dt, second_dose_dt, third_dose_dt, booster_dose_dt]

        for date in dates:
            dates.remove(date)
            for counter in range(0, len(dates)):
                if date and dates[counter] == date:
                    message = f'Duplicate entry for date {date}, please correct.'
                    raise ValidationError(message)

        self.compare_dates('first_dose_dt', ['second_dose_dt', 'third_dose_dt', 'booster_dose_dt'])
        self.compare_dates('second_dose_dt', ['third_dose_dt', 'booster_dose_dt'])
        self.compare_dates('third_dose_dt', ['booster_dose_dt'])

    def compare_dates(self, date_field, compared_to=[]):
        date = self.cleaned_data.get(date_field)
        for compare in compared_to:
            compare_dt = self.cleaned_data.get(compare)
            if (date and compare_dt) and date > compare_dt:
                message = {date_field:
                           f'The {date_field} can not be after the {compare}'}
                self._errors.update(message)
                raise ValidationError(message)

    def check_missing_date(self, cleaned_data, dates=[]):
        counter = 0
        for date in dates:
            curr_date = cleaned_data.get(date, '')
            if curr_date and counter > 0:
                for i in range(counter):
                    prev_date = cleaned_data.get(dates[i], '')
                    if not prev_date:
                        message = {dates[i]:
                                   f'Can not complete {date} before the '
                                   f'previous dose(s). {dates[i]}'}
                        self._errors.update(message)
                        raise ValidationError(message)
            counter += 1

    def validate_prev_immunization_received(self, cleaned_data=None):
        received_vaccine_name = cleaned_data.get('received_vaccine_name')
        first_dose_dt = cleaned_data.get('first_dose_dt')
        second_dose_dt = cleaned_data.get('second_dose_dt')
        third_dose_dt = cleaned_data.get('third_dose_dt')
        booster_dose_dt = cleaned_data.get('booster_dose_dt')
        try:
            received_vaccine = self.vaccines_received_cls.objects.get(
                ~Q(child_immunization_history=cleaned_data.get('child_immunization_history')),
                child_immunization_history__child_visit__subject_identifier=cleaned_data.get(
                    'child_immunization_history').child_visit.subject_identifier,
                received_vaccine_name=received_vaccine_name,
                first_dose_dt=first_dose_dt,
                second_dose_dt=second_dose_dt,
                third_dose_dt=third_dose_dt,
                booster_dose_dt=booster_dose_dt)
        except self.vaccines_received_cls.DoesNotExist:
            pass
        else:
            visit_code = received_vaccine.visit.visit_code
            current_visit = cleaned_data.get('child_immunization_history').child_visit.visit_code
            if current_visit and current_visit != visit_code:
                timepoint = received_vaccine.visit.visit_code_sequence
                message = {'received_vaccine_name':
                           f'{received_vaccine_name} vaccine with the same dates '
                           f'has already been captured at visit {visit_code}.{timepoint}'}
                self._errors.update(message)
                raise ValidationError(message)

    def validate_hpv_vaccine_adolescent(self, cleaned_data, ages={}):
        received_vaccine_name = cleaned_data.get('received_vaccine_name')
        if 'adolescent' in ages.values():
            if received_vaccine_name != 'hpv_vaccine':
                msg = {'received_vaccine_name':
                       'Cannot select age as Adolescent if vaccine is not HPV.'}
                self._errors.update(msg)
                raise ValidationError(msg)
        if received_vaccine_name == 'hpv_vaccine':
            for hpv_field, hpv_age in ages.items():
                if hpv_age and hpv_age != 'adolescent':
                    msg = {hpv_field:
                           'HPV vaccine selected, child age should be adolescent.'}
                    self._errors.update(msg)
                    raise ValidationError(msg)

    def validate_vaccination_at_birth(self, cleaned_data=None, ages={}):
        if cleaned_data.get('received_vaccine_name') == 'bcg':
            for field, age in ages.items():
                if age and age not in ['At Birth', 'After Birth']:
                    msg = {field:
                           'BCG vaccination is ONLY given at birth or few'}
                self._errors.update(msg)
                raise ValidationError(msg)

    def validate_hepatitis_vaccine(self, cleaned_data=None, ages={}):
        if cleaned_data.get('received_vaccine_name') == 'hepatitis_b':
            for field, age in ages.items():
                if age and age not in ['At Birth', '2', '3', '4']:
                    msg = {field:
                           'Hepatitis B can only be administered '
                           'at birth or 2 or 3 or 4 months of infant life'}
                    self._errors.update(msg)
                    raise ValidationError(msg)

    def validate_dpt_vaccine(self, cleaned_data=None, ages={}):
        if cleaned_data.get('received_vaccine_name') == 'dpt':
            for field, age in ages.items():
                if age and age not in ['2', '3', '4']:
                    msg = {field:
                           'DPT. Diphtheria, Pertussis and Tetanus can only '
                           'be administered at 2 or 3 or 4 months ONLY.'}
                    self._errors.update(msg)
                    raise ValidationError(msg)

    def validate_haemophilus_vaccine(self, cleaned_data=None, ages={}):
        if cleaned_data.get('received_vaccine_name') == 'haemophilus_influenza':
            for field, age in ages.items():
                if age and age not in ['2', '3', '4']:
                    msg = {field:
                           'Haemophilus Influenza B vaccine can only be given '
                           'at 2 or 3 or 4 months of infant life.'}
                    self._errors.update(msg)
                    raise ValidationError(msg)

    def validate_pcv_vaccine(self, cleaned_data=None, ages={}):
        if cleaned_data.get('received_vaccine_name') == 'pcv_vaccine':
            for field, age in ages.items():
                if age and age not in ['2', '3', '4']:
                    msg = {field:
                           'The PCV [Pneumonia Conjugated Vaccine], can ONLY be'
                           ' administered at 2 or 3 or 4 months of infant life.'}
                    self._errors.update(msg)
                    raise ValidationError(msg)

    def validate_polio_vaccine(self, cleaned_data=None, ages={}):
        if cleaned_data.get('received_vaccine_name') == 'polio':
            for field, age in ages.items():
                if age and age not in ['2', '3', '4', '18']:
                    msg = {field:
                           'Polio vaccine can only be administered at '
                           '2 or 3 or 4 or 18 months of infant life'}
                    self._errors.update(msg)
                    raise ValidationError(msg)

    def validate_rotavirus_vaccine(self, cleaned_data=None, ages={}):
        if cleaned_data.get('received_vaccine_name') == 'rotavirus':
            for field, age in ages.items():
                if age and age not in ['2', '3']:
                    msg = {field:
                           'Rotavirus is only administered at 2 or 3 months '
                           'of infant life'}
                    self._errors.update(msg)
                    raise ValidationError(msg)

    def validate_measles_vaccine(self, cleaned_data=None, ages={}):
        if cleaned_data.get('received_vaccine_name') == 'measles':
            for field, age in ages.items():
                if age and age not in ['9', '18']:
                    msg = {field:
                           'Measles vaccine is only administered at 9 or 18 '
                           'months of infant life.'}
                    self._errors.update(msg)
                    raise ValidationError(msg)

    def validate_pentavalent_vaccine(self, cleaned_data=None, ages={}):
        if cleaned_data.get('received_vaccine_name') == 'pentavalent':
            for field, age in ages.items():
                if age and age not in ['2', '3', '4']:
                    msg = {field:
                           'The Pentavalent vaccine can only be administered '
                           'at 2 or 3 or 4 months of infant life.'}
                    self._errors.update(msg)
                    raise ValidationError(msg)

    def validate_vitamin_a_vaccine(self, cleaned_data=None, ages={}):
        if cleaned_data.get('received_vaccine_name') == 'vitamin_a':
            for field, age in ages.items():
                if age and age not in ['6-11', '9', '9-12', '12-17', '18',
                                       '18-29', '24-29', '30-35', '36-41',
                                       '42-47']:
                    msg = {field:
                           'Vitamin A is given to children between 6-41 months'
                           ' of life'}
                    self._errors.update(msg)
                    raise ValidationError(msg)

    def validate_ipv_vaccine(self, cleaned_data=None, ages={}):
        if cleaned_data.get('received_vaccine_name') == 'inactivated_polio_vaccine':
            for field, age in ages.items():
                if age and age not in ['4', '9-12']:
                    msg = {field:
                           'IPV vaccine is only given at 4 Months. '
                           'of life or 9-12 months'}
                    self._errors.update(msg)
                    raise ValidationError(msg)

    def validate_diptheria_tetanus_vaccine(self, cleaned_data=None, ages={}):
        if cleaned_data.get('received_vaccine_name') == 'diphtheria_tetanus':
            for field, age in ages.items():
                if age and age not in ['18']:
                    msg = {field:
                           'Measles vaccine is only administered at 18 '
                           'months of infant life.'}
                    self._errors.update(msg)
                    raise ValidationError(msg)
