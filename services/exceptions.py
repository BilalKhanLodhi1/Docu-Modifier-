class DocuCraftError(Exception):
    """An error whose message is safe to show to end users."""


class UnsupportedFileError(DocuCraftError):
    pass


class DependencyMissingError(DocuCraftError):
    pass


class AIProviderError(DocuCraftError):
    pass
