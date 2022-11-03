import typing

import marshmallow as ma


class UnionField(ma.fields.Field):
    """Field that deserializes multi-type input data to app-level objects."""

    def __init__(self, val_types: typing.List[ma.fields.Field], **kwargs):
        self.valid_types = val_types
        super().__init__(**kwargs)

    def _deserialize(
            self, value: typing.Any, attr: str = None, data: typing.Mapping[str, typing.Any] = None, **kwargs
    ):
        """
        _deserialize defines a custom Marshmallow Schema Field that takes in multi-type input data to
        app-level objects.

        Parameters
        ----------
        value : {Any}
            The value to be deserialized.

        Keyword Parameters
        ----------
        attr : {str} [Optional]
            The attribute/key in data to be deserialized. (default: {None})
        data : {Optional[Mapping[str, Any]]}
            The raw input data passed to the Schema.load. (default: {None})

        Raises
        ----------
        ValidationError : Exception
            Raised when the validation fails on a field or schema.
        """
        errors = []
        # iterate through the types being passed into UnionField via val_types
        for field in self.valid_types:
            try:
                # inherit deserialize method from Fields class
                return field.deserialize(value, attr, data, **kwargs)
            # if error, add error message to error list
            except ma.ValidationError as error:
                errors.append(error.messages)
        if errors:
            raise ma.ValidationError(errors)
