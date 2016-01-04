import os.path
import random
import pickle
from jsonschema import Draft4Validator, validators, ValidationError


def save_obj(obj, file_path):
    with open(file_path, 'wb') as f:
        pickle.dump(obj, f, pickle.HIGHEST_PROTOCOL)


def load_obj(file_path):
    with open(file_path, 'rb') as f:
        return pickle.load(f)


class ExtendedValidationError(ValidationError):
    def __init__(self, *args, **kwargs):
        self.property = kwargs.pop('property', None)
        super().__init__(*args, **kwargs)

    def get_property(self):
        return self.property

    def get_property_schema(self):
        properties = self.schema.get('properties', {})
        return properties.get(self.get_property(), {})

    def get_root_instance(self):
        return self.instance

    def get_root_schema(self):
        return self.schema

    def get_property_path(self):
        return tuple(self.path) + (self.property, )


class DefaultHandler(ExtendedValidationError):
    pass


class PropertyError(ExtendedValidationError):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._root_context = None

    def get_property(self):
        return self.path[len(self.path) - 1]

    def get_property_schema(self):
        return self.schema

    def get_root_instance(self):
        return self._root_context[1]

    def get_root_schema(self):
        return self._root_context[0]

    def get_property_path(self):
        return tuple(self.path)

    def with_root(self, schema, instance):
        self._root_context = (schema, instance)
        return self


class RequiredError(ExtendedValidationError):
    pass


class Question(object):
    SUPPORTED_TYPES = []

    _max_iterations = 5

    def __init__(self, default, prop_type, prop_enum, required, correction):
        self._default_value = default.get('value')
        self._correction = correction
        self._enum = prop_enum
        self._question = default.get('question')
        self._required = required
        self._type = prop_type

        if self._enum and default.get('show_choices'):
            self._choices = self._create_choices_str(self._enum, default.get('dictionary'))
        else:
            self._choices = None

    def __str__(self):
        question = 'question: "{}"'.format(self._question[:15])
        if len(self._question) > 15:
            question += '...'
        info = [question]
        if self._default_value:
            info.append('default: {}'.format(self._default_value))
        if self._required:
            info.append('required')

        return ', '.join(info)

    def ask(self, key_value=None):
        raise NotImplementedError

    @staticmethod
    def _create_choices_str(enum, dictionary=None):
        return ", ".join("{}. {}".format(index, dictionary and dictionary.get(choice) or choice)
                         for index, choice in enumerate(enum, start=1))


class ConsoleQuestion(Question):
    CMD_BREAK_ANSWER = "\q"
    MSG_CORRECTION = "Ошибка валидации\n"
    MSG_NOT_IN_ENUM = ("Такой ответ не входит в список возможных вариантов\n"
                       "Пожалуйста попробуйте еще раз или введите {} для выхода".format(CMD_BREAK_ANSWER))
    MSG_REQUIRED = "Это обязательный параметр. Попробуйте еще раз"
    MSG_CHOICES = "Выберите один из вариантов: {}"
    MSG_DEFAULT = "Ответ по умолчанию: {}"
    MSG_ITER_LIMIT = "Не получилось установить ответ, пропускаем"

    def ask(self, key_value=None):
        if self._correction:
            print(self.MSG_CORRECTION)
        print(self._question.format(default=self._default_value, key_value=key_value))
        for i in range(self._max_iterations):
            answer = self._input(self.MSG_CHOICES.format(self._choices) if self._choices else "")
            if answer == self.CMD_BREAK_ANSWER:
                answer = None
                break
            elif answer == '':
                if self._default_value:
                    print(self.MSG_DEFAULT.format(self._default_value))
                    answer = self._default_value
                    break
                elif not self._required:
                    break
                print(self.MSG_REQUIRED)
            elif self._enum:
                if answer in self._enum:
                    break
                try:
                    answer = self._enum[int(answer)]
                    break
                except TypeError:
                    pass
                print(self.MSG_NOT_IN_ENUM)
            else:
                break
        else:
            answer = ''
            print(self.MSG_ITER_LIMIT)

        return answer

    def _input(self, msg):
        return input(msg)


class AutoAnswers(ConsoleQuestion):

    MSG_RANDOM_ANSWER = "Случайный ответ: {}"

    def _input(self, msg):
        print(msg)
        random_answer = self._random_answer()
        print(self.MSG_RANDOM_ANSWER.format(random_answer))
        return random_answer

    def _random_answer(self):
        mapping = {"integer": lambda: random.randint(0, 1000),
                   "string": lambda: self._random_word(10),
                   "bool": lambda: random.choice([True, False])}
        if self._enum:
            return random.choice(self._enum)
        elif self._type in mapping:
            return mapping[self._type]()
        else:
            return ''

    @staticmethod
    def _random_word(length):
        letters = 'abcdefghijklmnopqrstuvwxyz'
        return ''.join(random.choice(letters) for i in range(length))


class QueristValidator(object):

    def __init__(self, schema, question_class=ConsoleQuestion, answers_file=None):
        if answers_file and os.path.isfile(answers_file):
            answers = load_obj(answers_file)
        else:
            answers = {}
        self._answers = answers if isinstance(answers, dict) else {}
        self._keys = {}
        self._make_question = question_class
        self._questions = {}
        self._schema = schema

        self.base_validator = Draft4Validator(self._schema)
        self.validator = self._extend_with_default(Draft4Validator)(self._schema)

    def validate(self, instance):
        for error in self.iter_errors(instance):
            raise error

    def dump_answers(self, answers_file):
        save_obj(self._answers, answers_file)

    def iter_errors(self, instance):
        self._questions = {}
        self._keys = {}
        for error in self.validator.iter_errors(instance, self._schema):
            if isinstance(error, ExtendedValidationError):
                is_required_error = type(error) is RequiredError
                property_name = error.get_property()
                subschema = error.get_property_schema()
                instance = error.get_root_instance()

                if is_required_error and not (isinstance(subschema, dict) and "default" in subschema):
                    yield error
                    continue
                self._resolve_default(error)  # здесь изменяется instance
                if is_required_error and property_name not in instance:
                    yield error
                elif property_name in instance:
                    yield from self.base_validator.iter_errors(instance[property_name], subschema)
                    # todo поправлять path, проверить ErrorTree
                    # todo отложенно проверять измененные экземпляры

            else:
                yield error

    def _resolve_default(self, error):
        """ Измененяет инстанс по инструкциям в default.

        Returns:
            Если default не задан возвращает False, иначе True
        """
        required = isinstance(error, RequiredError)
        path = error.get_property_path()
        property_name = error.get_property()
        property_schema = error.get_property_schema()

        if path not in self._questions:
            default = property_schema.get('default')
            if not isinstance(default, dict):
                self._questions[path] = None
                return False
            if 'question' in default:
                question = self._make_question(default,
                                               property_schema.get('type'),
                                               property_schema.get('enum'),
                                               required,
                                               type(error) != DefaultHandler)
            else:
                question = None
            default_value = default.get('value', None)
            self._questions[path] = question, default_value
        else:
            question, default_value = self._questions[path]

        error.get_root_instance()[property_name] = self._ask(path, error, question) if question else default_value
        return True

    def _ask(self, path, error, question):
        key_path = path[:-1]
        if key_path in self._answers:
            answers = self._answers[key_path]
        else:
            self._answers[key_path] = answers = {}

        if key_path in self._keys:
            key = self._keys[key_path]
        else:
            self._keys[key_path] = key = self._get_key(error.get_root_schema().get('properties', {}))

        key_value = error.get_root_instance()[key]

        prop = error.get_property()

        if key_value is not None:
            if key_value in answers:
                yet_answered = answers.get(key_value, {})
            else:
                yet_answered = answers[key_value] = {}

            if prop in yet_answered:
                return yet_answered[prop]

            answer = question.ask(key_value)
            if answer is not None:
                yet_answered[prop] = answer
        else:
            answer = question.ask()

        return answer

    @staticmethod
    def _get_key(properties):
        for prop, subschema in properties.items():
            default = subschema.get("default") if isinstance(subschema, dict) else None
            if isinstance(default, dict):
                key_field = default.get("key_field")
                if key_field:
                    return prop
        else:
            return None

    @staticmethod
    def _extend_with_default(validator_class):
        validate_properties = validator_class.VALIDATORS["properties"]

        def set_defaults(validator, properties, instance, schema):
            for prop, subschema in properties.items():
                if prop not in instance and "default" in subschema:
                    yield DefaultHandler("HandleDefault", property=prop)

            for error in validate_properties(validator, properties, instance, schema, ):
                if type(error) is ValidationError:
                    yield PropertyError.create_from(error).with_root(schema, instance)
                else:
                    yield error

        def required_default_d4(validator, required, instance, schema):
            if not validator.is_type(instance, "object"):
                return

            for prop in required:
                if prop not in instance:
                    yield RequiredError("%r is a required property" % prop, property=prop)

        return validators.extend(validator_class, {"properties": set_defaults,
                                                   "required": required_default_d4})
