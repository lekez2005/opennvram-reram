# https://stackoverflow.com/questions/3615565/python-get-constructor-to-return-an-existing-object-instead-of-a-new-one/33458129


class Unique(type):

    def __call__(cls, *args, **kwargs):
        name = cls.get_name(*args, **kwargs)
        if name not in cls._cache:
            self = cls.__new__(cls, *args, **kwargs)
            self.name = name
            cls.__init__(self, *args, **kwargs)
            cls._cache[name] = self
        return cls._cache[name]

    def __init__(cls, name, bases, attributes):
        super().__init__(name, bases, attributes)
        cls._cache = {}

    @classmethod
    def get_name(mcs, *args, **kwargs):
        raise NotImplementedError("Classes must implement get_name method to determine uniqueness")
