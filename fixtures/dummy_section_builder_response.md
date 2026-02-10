```json
{
  "section": "Python Lists: Storing Collections of Data",
  "items": [
    { "markdown": ["Python lists are ordered, mutable collections used to store multiple items under one variable. They can hold different data types like numbers, strings, and even other lists."] },
    { "markdown": ["**Note:** Lists use square brackets [] and items are separated by commas."] },
    { "markdown": ["**Warning:** Lists are zero-indexed, so the first element is at index 0."] },
    { "codeEditor": ["# Creating a list\nmy_list = [1, 2, 3, \"apple\", \"banana\", True]\n\n# Accessing elements\nmy_list[0]      # first element\nmy_list[-1]     # last element\n\n# Slicing\nmy_list[1:4]\n\n# Modifying elements\nmy_list[0] = 100\n\n# Adding elements\nmy_list.append(\"cherry\")\nmy_list.insert(1, \"orange\")\n\n# Removing elements\nmy_list.remove(\"apple\")\npopped_item = my_list.pop(0)", "python", false, [1, 3]] },
    { "markdown": ["- Lists are ordered and mutable\n- They can store mixed data types\n- Elements are accessed using zero-based indexing\n- Common methods: append(), insert(), remove(), pop()"] },
    { "flip": [
        "What does mutable mean for lists?",
        "You can change, add, or remove items after creation",
        "Think about editing after creation",
        "Lists can be modified anytime"
      ]
    },
    { "blank": [
        "To add an item to the end of a list, use ___.",
        "append()",
        "It adds a new element after the last item",
        "append() places a new element at the end of the list"
      ]
    },
    { "freeText": [
        "Write Python code to create a fruits list and modify it as described.",
        "",
        "",
        "en",
        "apple,banana,orange,grape,strawberry,kiwi",
        "multi"
      ]
    },
    {
      "quiz": {
        "title": "Python Lists Check",
        "questions": [
          {
            "q": "Which feature allows lists to change size?",
            "c": ["Ordering", "Mutability", "Indexing"],
            "a": 1,
            "e": "Mutability means elements can be added, removed, or changed."
          },
          {
            "q": "How do you access the fifth element of my_data?",
            "c": ["my_data[5]", "my_data[4]", "my_data[-5]"],
            "a": 1,
            "e": "Lists are zero-indexed, so index 4 is the fifth element."
          },
          {
            "q": "Which method adds an item to the end of a list?",
            "c": ["insert()", "add()", "append()"],
            "a": 2,
            "e": "append() always adds an element to the end of the list."
          },
          {
            "q": "True or False: Lists cannot change size after creation.",
            "c": ["True", "False"],
            "a": 1,
            "e": "Lists are mutable, so their size can change."
          }
        ]
      }
    },
    { "markdown": ["**Success:** You can confidently create, access, and modify Python lists."] }
  ]
}
```
