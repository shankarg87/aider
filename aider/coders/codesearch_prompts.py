from .editblock_prompts import EditBlockPrompts


class CodeSearchPrompts(EditBlockPrompts):

    tool_use = """ Use the tool calling functionality provided to help with code analysis to search and find the relevant code to modify.
    There may be several code analysis tools that are provided.
    """