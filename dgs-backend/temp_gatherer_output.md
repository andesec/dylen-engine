# Intermediate Data Model (IDM) for "Introduction to Python: Lists and Loops"

## Domain
Technical/Coding

## Core Concepts

### 1. Python Lists
*   **Definition**: An ordered, mutable collection of items. Lists can hold items of different data types.
*   **Creation**: How to declare and initialize a list.
*   **Indexing**: Accessing elements by their position (index), starting from 0.
*   **Slicing**: Extracting a portion (sub-list) from a list.
*   **Modification**: Adding, removing, or changing elements in a list.
*   **Common List Methods**: `append()`, `insert()`, `remove()`, `pop()`, `len()`.

### 2. Python Loops
*   **Purpose**: Repeating a block of code multiple times.
*   **`for` Loops**:
    *   Iterating over sequences (like lists, strings, `range()`).
    *   Using the `range()` function to generate a sequence of numbers for iteration.
*   **`while` Loops**:
    *   Repeating code as long as a condition is `True`.
    *   Importance of controlling the loop condition to prevent infinite loops.
*   **Loop Control Statements (Brief)**: `break` (exit loop), `continue` (skip current iteration). (Mention, but don't go deep for highlights).

### 3. Combining Lists and Loops
*   Iterating through list elements using both `for` and `while` loops.
*   Performing operations on each element of a list using loops.

## Vocabulary/Key Terms

*   **List**: An ordered, mutable collection of items in Python.
*   **Element**: An individual item stored within a list.
*   **Index**: The numerical position of an element in a list, starting from 0.
*   **Mutable**: Refers to data types whose values can be changed after creation (e.g., lists).
*   **Immutable**: Refers to data types whose values cannot be changed after creation (e.g., numbers, strings).
*   **Iteration**: The process of repeatedly executing a block of code, typically for each item in a sequence.
*   **Loop**: A control flow statement that allows code to be executed repeatedly.
*   **`for` loop**: A loop used for iterating over a sequence (like a list) or other iterable objects.
*   **`while` loop**: A loop that continues to execute its block of code as long as a specified condition is true.
*   **`range()`**: A built-in Python function that generates a sequence of numbers, often used with `for` loops.
*   **`append()`**: A list method that adds an element to the end of a list.
*   **`len()`**: A built-in Python function that returns the number of items (length) of an object, like a list.

## Examples

### 1. Python Lists
```python
# Creating a list
fruits = ["apple", "banana", "cherry"]
numbers = [1, 5, 2, 8]
mixed_list = ["hello", 123, True]

# Accessing elements
print(fruits[0]) # Output: apple
print(numbers[2]) # Output: 2

# Negative indexing (from the end)
print(fruits[-1]) # Output: cherry

# Slicing
print(numbers[1:3]) # Output: [5, 2]
print(fruits[:2]) # Output: ['apple', 'banana']

# Modifying elements
fruits[1] = "orange"
print(fruits) # Output: ['apple', 'orange', 'cherry']

# Adding elements with append()
fruits.append("grape")
print(fruits) # Output: ['apple', 'orange', 'cherry', 'grape']

# Getting the length of a list
list_length = len(fruits)
print(list_length) # Output: 4
```

### 2. Python Loops

#### `for` Loop with a List
```python
fruits = ["apple", "banana", "cherry"]

# Iterating directly over elements
print("Iterating through fruits:")
for fruit in fruits:
    print(fruit)

# Iterating using range() and index
print("\nIterating through fruits using index:")
for i in range(len(fruits)):
    print(f"Index {i}: {fruits[i]}")
```

#### `for` Loop with `range()`
```python
# Printing numbers from 0 to 4
print("Numbers from 0 to 4:")
for i in range(5):
    print(i)

# Printing numbers from 2 to 6
print("\nNumbers from 2 to 6:")
for i in range(2, 7):
    print(i)
```

#### `while` Loop
```python
count = 0
print("Counting up to 3:")
while count < 3:
    print(count)
    count += 1 # Increment count to eventually stop the loop

# Example of using while with a list (less common than for, but possible)
index = 0
numbers = [10, 20, 30]
print("\nWhile loop with list:")
while index < len(numbers):
    print(numbers[index])
    index += 1
```

## Interactive Elements

1.  **Multiple Choice Quiz (Core Concepts - Lists)**
    *   "Which of the following is true about Python lists?"
        *   A) They are immutable.
        *   B) They are ordered collections.
        *   C) They can only store numbers.
        *   D) Elements cannot be changed after creation.
        *   *(Correct Answer: B)*
    *   "What is the index of the element 'banana' in the list `['apple', 'banana', 'cherry']`?"
        *   A) 1
        *   B) 0
        *   C) 2
        *   D) -1
        *   *(Correct Answer: A)*

2.  **Fill-in-the-Blanks (Vocabulary/Key Terms)**
    *   "To add an element to the end of a list, you use the `________` method." *(Answer: append)*
    *   "A `________` loop is used to repeat a block of code a specific number of times or for each item in a sequence." *(Answer: for)*
    *   "The `________` function is useful for generating a sequence of numbers to iterate over." *(Answer: range)*

3.  **Code Completion (Examples - Lists)**
    *   **Prompt**: "Complete the code to create a list named `colors` with 'red', 'green', and 'blue', then print the first element."
        ```python
        colors = ["red", "green", "blue"]
        print(_____[0])
        ```
        *(Expected Completion: `colors`)*
    *   **Prompt**: "Add 'yellow' to the end of the `colors` list."
        ```python
        colors = ["red", "green", "blue"]
        colors.____("yellow")
        print(colors)
        ```
        *(Expected Completion: `append`)*

4.  **Code Completion (Examples - Loops)**
    *   **Prompt**: "Complete the `for` loop to print each `fruit` in the `fruits` list."
        ```python
        fruits = ["apple", "banana", "cherry"]
        for fruit ____ fruits:
            print(fruit)
        ```
        *(Expected Completion: `in`)*
    *   **Prompt**: "Complete the `while` loop to print numbers from 0 up to, but not including, 5."
        ```python
        count = 0
        while count < 5:
            print(count)
            count ____ 1
        ```
        *(Expected Completion: `+=`)*

5.  **Output Prediction**
    *   **Prompt**: "What will be the output of the following code?"
        ```python
        my_list = [10, 20, 30]
        my_list[1] = 25
        print(my_list)
        ```
        *(Expected Output: `[10, 25, 30]`)*
    *   **Prompt**: "What will be the output of this loop?"
        ```python
        for x in range(3):
            print(x * 2)
        ```
        *(Expected Output: `0` then `2` then `4` on separate lines)*