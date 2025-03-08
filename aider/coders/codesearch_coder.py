from .editblock_coder import EditBlockCoder
import jedi
from typing import Tuple
from tree_sitter import Language, Parser
import tree_sitter_python as tspython
from .codesearch_prompts import CodeSearchPrompts
import os
import json

class CodeSearchCoder(EditBlockCoder):
    "A coder that relies on codesearch"
    edit_format = "codesearch"
    gpt_prompts = CodeSearchPrompts()
    functions = [
        dict(
            name="get_definition",
            description="Inspect the definition of a function or class or a general symbol that you see in a particular file",
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
            description="Inspect snippets of code that reference a particular symbol that you see in a particular file",
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
            name="read_files",
            description="Get the contents of multiple files",
            parameters=dict(
                type="object",
                properties=dict(
                    file_paths=dict(
                        type="array",
                        items=dict(
                            type="string",
                            description="File path",
                        ),
                    ),
                ),
                required=["file_paths"],
                additionalProperties=False,
            ),
        ),
        dict(
            name="list",
            description="List contents of a directory",
            parameters=dict(
                type="object",
                properties=dict(
                    dir_path=dict(
                        type="string",
                        description="Directory path",
                    ),
                ),
                required=["dir_path"],
                additionalProperties=False,
            ),
        ),
        dict(
            name="add_files",
            description="Add final files where edit needs to be performed.",
            parameters=dict(
                type="object",
                properties=dict(
                    file_paths=dict(
                        type="array",
                        items=dict(
                            type="string",
                            description="File path",
                        ),
                    ),
                ),
                required=["file_paths"],
                additionalProperties=False,
            ),            
        ),
        dict(
            name="grep",
            description="Find all files that contain occurence of a particular text",
            parameters=dict(
                type="object",
                properties=dict(
                    text=dict(
                        type="string",
                        description="text that you need to search for",
                    ),
                    dir_path=dict(
                        type="string",
                        description="directory in which you want to search",
                    ),
                ),
                required=["text, dir_path"],
                additionalProperties=False,
            ),       
        ),        
    ]

    def get_references(self, file_path, line_number, column_number):
        # Tl;DR use jedi to dump to the references of the symbol.
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"The file {file_path} does not exist.")
        if not os.path.isfile(file_path):
            raise IsADirectoryError(f"The path {file_path} is not a file.")
        if not file_path.endswith(('.py', '.txt')):
            raise ValueError(f"The file {file_path} is not a valid text file.")
                
        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()
        jedi_project = jedi.Project(self.repo_map.root, sys_path=None)
        script = jedi.Script(code, path=file_path, project=jedi_project)
        references = script.get_references(line_number, column_number)
        return [dump_reference(r) for r in references]   
        

    def get_definition(self, file_path, line_number, column_number):
        # Tl;DR use jedi to dump to the definition of the symbol. Then use tree-sitter to identify beginning and end of the definition.
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"The file {file_path} does not exist.")
        if not os.path.isfile(file_path):
            raise IsADirectoryError(f"The path {file_path} is not a file.")
        if not file_path.endswith(('.py', '.txt')):
            raise ValueError(f"The file {file_path} is not a valid text file.")
        
        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()
        jedi_project = jedi.Project(self.repo_map.root, sys_path=None)
        script = jedi.Script(code, path=file_path, project=jedi_project)
        definitions = script.goto(line_number, column_number)

        # Resolve the original definition recursively
        original_definition = resolve_original_definition(definitions, jedi_project)
        return dump_definition(original_definition)
    
    def read_files(self, file_paths):
        content = []
        for file_path in file_paths:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"The file {file_path} does not exist.")
            if not os.path.isfile(file_path):
                raise IsADirectoryError(f"The path {file_path} is not a file.")
            if not file_path.endswith(('.py', '.txt')):
                raise ValueError(f"The file {file_path} is not a valid text file.")
            
            with open(file_path, "r", encoding="utf-8") as f:
                content.append({
                    "file_content": f.read(),
                    "file_path": file_path,
                })

        return content
        
    def list(self, dir_path):
        """ List all files in a directory """
        contents = []
        full_path = os.path.join(os.getcwd(), dir_path)
        
        if os.path.exists(full_path):
            for item in os.listdir(full_path):
                item_path = os.path.join(full_path, item)
                if os.path.isdir(item_path):
                    contents.append(f"Directory: {item}")
                else:
                    contents.append(f"File: {item}")
        else:
            raise FileNotFoundError(f"The directory {full_path} does not exist.")
        
        return contents
    
    def grep(self, text, dir_path):
        """Recursively search for text in Python files under a directory."""
        contents = []
        full_path = os.path.join(os.getcwd(), dir_path)

        if os.path.exists(full_path):
            for root, dirs, files in os.walk(full_path):
                for file in files:
                    if file.endswith(".py"):
                        file_path = os.path.join(root, file)
                        try:
                            with open(file_path, "r", encoding="utf-8") as f:
                                i = 0
                                for line in f:
                                    if text in line:
                                        contents.append({
                                            "filepath": file_path,
                                            "line_number": i,
                                            "content": line,
                                        })
                                    i += 1
                        except UnicodeDecodeError:
                            continue
        else:
            raise FileNotFoundError(f"The directory {full_path} does not exist.")

        return contents

    def preedit_tool_call(self, args, valid_tool_call = True) -> Tuple[bool, dict]:
        # Tl;DR: Process the codesearch request
        name = self.partial_response_function_call.get("name")
        content = ""
        tool_output = {}
        valid_call = True

        # TODO(shankgan): Raise appropriate exceptions here to inform assistant of bad function calls
        if name == "get_definition":
            content = json.dumps(self.get_definition(**args))
        elif name == "get_references":
            content = json.dumps(self.get_references(**args))
        elif name == "read_files":
            content = json.dumps(self.read_files(**args))
        elif name == "list":
            content = json.dumps(self.list(**args))
        elif name == "grep":
            content = json.dumps(self.grep(**args))
        elif name == "add_files":
            for file in args["file_paths"]:
                self.add_rel_fname(file)
            content = ""
        else:
            valid_call = False

        if valid_call:
            if valid_tool_call:
                tool_output = {"tool_call_id": self.partial_response_tool_calls[0]["id"], "content": content}
            else:
                tool_output = {"function_name": name, "content": content}
        return valid_call, tool_output

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

        return {
            "file_path": ref.module_path,
            "line": ref.line,
            "column": ref.column,
            "relevant_code": surrounding_code
        }
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

        return {
            "name": definition.name,
            "type": definition.type,
            "module_path": definition.module_path,
            "line": definition.line,
            "column": definition.column,
            "code": code_snippet
        }
    return {
        "name": definition.name,
        "type": definition.type,
        "module_path": None,
        "line": None,
        "column": None,
        "code_snippet": None
    }

