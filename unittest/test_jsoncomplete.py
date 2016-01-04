import os
import unittest
import copy
import random
import json
from jsonschema import ValidationError
from jsoncomplete import QueristValidator, AutoAnswers, load_obj

SINGLE_TEST = False


class TestFixtures(unittest.TestCase):

    model = 'Account'

    @classmethod
    def setUpClass(cls):
        scheme_path = 'schemes/{}.json'
        with open(scheme_path.format(cls.model)) as schema_file:
            schema = json.load(schema_file)
        cls.validator = QueristValidator(schema, AutoAnswers)

    def setUp(self):
        self.validator._answers = {}
        self.test_case = {'fields': {}, 'model': 'finstat.{}'.format(self.model), 'pk': 1}

    @unittest.skipIf(SINGLE_TEST, 'Запускаем тесты выборочно\n')
    def test_iterator(self):
        """ Проверяем, что валидатор вообще работает """
        self.test_case['fields'] = {'account_name': 'valid',
                                    'account_type': 'OW',
                                    'currency': 'RUB',
                                    'initial_amount': 1000,
                                    'comment': 'valid',
                                    'fk_owner': 1}

        try:
            self.validator.validate(self.test_case)
        except ValidationError:
            self.fail("Ошибка валидации, возможно изменена схема")

    @unittest.skipIf(SINGLE_TEST, 'Запускаем тесты выборочно\n')
    def test_invalid_instance(self):
        """ Проверяем что невалидные значения будут исправленны. """
        self.test_case['fields'] = {'account_name': 'broken',
                                    'account_type': 'OOPS',
                                    'currency': 'Пиастры',
                                    'initial_amount': -1000,
                                    'comment': 'broken',
                                    'fk_owner': 1}

        try:
            self.validator.validate(self.test_case)
        except ValidationError:
            self.fail("Непредвиденные ошибки валидации"
                      .format('\n'.join(error.message
                                        for error in self.validator.base_validator.iter_errors(self.test_case))))

    @unittest.skipIf(SINGLE_TEST, 'Запускаем тесты выборочно\n')
    def test_missed_required(self):
        """ Проверяем что стреляет ошибка валидации. """
        # В test_case отсутствует обязательный параметр fk_owner,
        # для которого не предусмотрена обработка значения по умолчанию
        self.test_case['fields'] = {'account_name': 'missed_required',
                                    'account_type': 'OW',
                                    'currency': 'RUB',
                                    'initial_amount': 1000,
                                    'comment': 'broken'}

        with self.assertRaises(ValidationError):
            self.validator.validate(self.test_case)

    @unittest.skipIf(SINGLE_TEST, 'Запускаем тесты выборочно\n')
    def test_answers(self):
        """ Проверяем подстановку сохраненных ответов.

        при отсутствии в инстансе поля initial_amount его значение не будет запрошено,
            а будет установленно по умолчанию, поэтому сразу пропишем его в test_case
        """
        self.test_case['fields'] = {'account_name': 'answered',
                                    'initial_amount': 0,
                                    'fk_owner': 1}

        answers = {('fields', ): {'answered': {'account_type': 'CC',
                                               'currency': 'AMD',
                                               'comment': "ok"}}}

        should_be = copy.deepcopy(self.test_case)
        should_be['fields'].update(answers[('fields', )]['answered'])

        saved_answers = self.validator._answers
        self.validator._answers = answers
        self.validator.validate(self.test_case)
        self.validator._answers = saved_answers
        self.assertDictEqual(self.test_case, should_be)

    @unittest.skipIf(SINGLE_TEST, 'Запускаем тесты выборочно\n')
    def test_ask(self):
        """ Проверяем ответы на вопросы
        
        ответы генерируются автоматически
        при отсутствии в инстансе поля initial_amount его значение не будет запрошено,
            а будет установленно по умолчанию, поэтому сразу пропишем его в test_case

        """
        self.test_case['fields'] = {'account_name': 'ask',
                                    'initial_amount': 0,
                                    'fk_owner': 1}

        duplicate = self.test_case['fields'].copy()
        self.validator.validate(self.test_case)
        duplicate.update(self.validator._answers[('fields',)]['ask'])

        self.assertDictEqual(self.test_case['fields'], duplicate)

    @unittest.skipIf(SINGLE_TEST, 'Запускаем тесты выборочно\n')
    def test_lookup_question_instance(self):
        """ Проверка кэширования обектов Question """
        self.test_case['fields'] = {'account_name': 'random',
                                    'initial_amount': 0,
                                    'fk_owner': 1}
        collection_saved = self.validator._questions
        self.validator._questions = {}
        for x in range(3):
            test_case = copy.deepcopy(self.test_case)
            test_case['fields']['account_name'] = 'random{}'.format(random.randint(0, 1000))
            self.validator.validate(test_case)
        # print('Collected: ', ', '.join(key for key in self.validator._question._collection))
        # Сколько вопросов кэшировано
        collected_len = len(self.validator._questions)
        # Сколько свойств в схеме
        schema_len = len(self.validator._schema['properties']['fields']['properties'])
        # Сколько свойств определено в test_case (должны быть определены все для которых не вызывается default)
        defined_len = len(self.test_case['fields'])

        self.validator._questions = collection_saved
        self.assertEqual(collected_len, schema_len - defined_len)

    @unittest.skipIf(SINGLE_TEST, 'Запускаем тесты выборочно\n')
    def test_account_none(self):
        """ Проверка, что для None тоже запрашивается значение

        Механизм в этом случае срабатывает по ошибкам валидации, а не отсутствующим значениям
        """
        self.test_case['fields'] = {'account_name': 'none',
                                    'account_type':  None,
                                    'currency': None,
                                    'initial_amount': None,
                                    'comment': None,
                                    'fk_owner': 1}
        self.validator.validate(self.test_case)
        self.assertNotIn(None, self.test_case['fields'].values())

    @unittest.skipIf(True, 'Этот тест нужно выполнять на другой модели\n')
    def test_account_fail_no_key_field(self):
        """ Проверка, что будет, если не задан key_field """
        # todo выполнять на другой модели
        self.test_case['fields'] = {"account_type": "AN",
                                    "currency": "USD",
                                    "initial_amount": 10,
                                    "comment": "test",
                                    "fk_owner": 1}
        self.validator.validate(self.test_case)
        self.assertNotIn(None, self.test_case['fields'].values())

    @unittest.skipIf(SINGLE_TEST, 'Запускаем тесты выборочно\n')
    def testAnswersFile(self):
        def validate(validator, index):
            test_case_copy = copy.deepcopy(self.test_case)
            test_case_copy['fields']['account_name'] = "fileIO_{}".format(index)
            validator.validate(test_case_copy)

        answers_file = 'output/test.json'
        self.test_case['fields'] = {"account_name": "fileIO",
                                    "fk_owner": 1}

        for x in range(3):
            validate(self.validator, x)

        self.validator.dump_answers(answers_file)

        new_validator = QueristValidator(self.validator._schema, AutoAnswers, answers_file)
        for x in range(3):
            validate(new_validator, x)

        answers = load_obj(answers_file)
        os.remove(answers_file)

        self.assertDictEqual(answers, self.validator._answers)

    @classmethod
    def tearDownClass(cls):
        pass

if __name__ == '__main__':
    unittest.main(verbosity=2)
