from .editblock_coder import EditBlockCoder
import jedi
from tree_sitter import Language, Parser
import tree_sitter_python as tspython


class CodeSearchCoder(EditBlockCoder):
    "A coder that relies on codesearch"
    edit_format = "codesearch"
    functions = [
        dict(
            name="get_definition",
            description="get the definition of a function or class or a general symbol that you see in a particular file",
            parameters=dict(
                type="object",
                properties=dict(
                    file_path=dict(
                        type="string",
                        description="File where you observe the symbol",
                    ),
                    line_number=dict(
                        type="integer",
                        description="Line number where you observe the symbol",
                    ),
                    column_number=dict( 
                        type="integer",
                        description="Column number where you observe the symbol",
                    ),
                ),
                required=["file_path, line_number, column_number"],
                additionalProperties=False,
            ),
        ),
        dict(
            name="get_references",
            description="get snippets of code that reference the symbol in question",
            parameters=dict(
                type="object",
                properties=dict(
                    file_path=dict(
                        type="string",
                        description="File where you observe the symbol",
                    ),
                    line_number=dict(
                        type="integer",
                        description="Line number where you observe the symbol",
                    ),
                    column_number=dict( 
                        type="integer",
                        description="Column number where you observe the symbol",
                    ),
                ),
                required=["file_path, line_number, column_number"],
                additionalProperties=False,
            ),
        ),
        dict(
            name="read_file",
            description="get contents of a file",
            parameters=dict(
                type="object",
                properties=dict(
                    file_path=dict(
                        type="string",
                        description="File where you observe the symbol",
                    ),
                ),
                required=["file_path"],
                additionalProperties=False,
            ),
        ),        
        # Pending functions: read_file, list_all_files, text_to_symbols (to map text to simple using RAG + Vector search)
    ]

    def init_index(self):
        # Tl;DR: Initialize the Jedi project for the repository.
        self.jedi_project = jedi.Project(self.repo_map.root, sys_path=None)

    def get_references(self, file_path, line_number, column_number):
        # Tl;DR use jedi to dump to the references of the symbol.
        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()

        script = jedi.Script(code, path=file_path, project=self.jedi_project)
        references = script.get_references(line_number, column_number)
        return [dump_reference(r) for r in references]       
        

    def get_definition(self, file_path, line_number, column_number):
        # Tl;DR use jedi to dump to the definition of the symbol. Then use tree-sitter to identify beginning and end of the definition.
        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()

        script = jedi.Script(code, path=file_path, project=self.jedi_project)
        definitions = script.goto(line_number, column_number)

        # Resolve the original definition recursively
        original_definition = resolve_original_definition(definitions, self.jedi_project)
        return dump_definition(original_definition)
    
    def read_file(self, file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return str({
                "file": f.read(),
                "file_path": file_path,
            })
    
    def process_codesearch(self, args) -> str:
        # Tl;DR: Process the codesearch request
        name = self.partial_response_function_call.get("name")

        if name == "get_definition":
            return self.get_definition(**args)
        elif name == "get_references":
            return self.get_references(**args)
        elif name == "read_file":
            return self.read_file(**args)
        else:
            raise ValueError(f'Unknown function_call name="{name}"')

def resolve_original_definition(definitions, project, visited=None):
    """
    Recursively resolve the original definition of a symbol.

    :param definitions: List of definitions from Jedi's `goto`.
    :param project: Jedi Project instance for context.
    :return: The original definition (or the best approximation).
    """
    if not definitions:
        return None

    if visited is None:
        visited = set()

    for definition in definitions:
        if hasattr(definition, 'is_builtin') and definition.is_builtin():
            # Stop recursion for built-in symbols
            return definition

        if definition.module_path and definition.line:
            # Check if the definition is in an external module or project file
            with open(definition.module_path, "r", encoding="utf-8") as f:
                code = f.read()

            script = jedi.Script(
                code, path=definition.module_path, project=project
            )
            new_definitions = script.goto(definition.line, definition.column)

            # Recursively resolve new definitions
            if new_definitions and new_definitions != definitions:
                def_key = (definition.module_path, definition.line, definition.column)
                if def_key not in visited:
                    visited.add(def_key)
                    return resolve_original_definition(new_definitions, project, visited)

    # If no further resolution, return the current definition
    return definitions[0]


def dump_reference(ref, context_lines=3):
    """ Dump a reference object to a JSON-serializable format. """
    if ref.module_path:
        with open(ref.module_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        start_line = max(ref.line - context_lines - 1, 0)
        end_line = min(ref.line + context_lines, len(lines))
        surrounding_code = ''.join(lines[start_line:end_line])

        return str({
            "file_path": ref.module_path,
            "line": ref.line,
            "column": ref.column,
            "relevant_code": surrounding_code
        })
    return ""

def dump_definition(definition) -> str:
    if definition.module_path and definition.line:
        with open(definition.module_path, "r", encoding="utf-8") as f:
            code = f.read()
        py_language = Language(tspython.language())
        parser = Parser(py_language)
        tree = parser.parse(bytes(code, "utf8"))

        node = tree.root_node.descendant_for_point_range(
            (definition.line - 1, definition.column),
            (definition.line - 1, definition.column)
        )

        while node and node.type != 'function_definition' and node.type != 'class_definition':
            node = node.parent

        if node:
            start_byte = node.start_byte
            end_byte = node.end_byte
            code_snippet = code[start_byte:end_byte]
        else:
            code_snippet = ""

        return str({
            "name": definition.name,
            "type": definition.type,
            "module_path": definition.module_path,
            "line": definition.line,
            "column": definition.column,
            "code": code_snippet
        })
    return str({
        "name": definition.name,
        "type": definition.type,
        "module_path": None,
        "line": None,
        "column": None,
        "code_snippet": None
    })

