Section 1 - Python Lists: Storing Collections of Data
Summary Python lists are ordered, mutable collections of items. They are one of the most versatile and widely used data structures in Python, allowing you to store a sequence of different data types (numbers, strings, even other lists) under a single variable. Lists are defined by enclosing elements in square brackets `[]`, with each element separated by a comma.

Data
# Creating a list
my_list = [1, 2, 3, "apple", "banana", True]
print(f"Original list: {my_list}")

# Accessing elements (lists are zero-indexed)
print(f"First element: {my_list[0]}")  # Output: 1
print(f"Third element: {my_list[2]}")  # Output: 3
print(f"Last element: {my_list[-1]}") # Output: True

# Slicing a list
print(f"Slice from index 1 to 3 (exclusive): {my_list[1:4]}") # Output: [2, 3, 'apple']

# Modifying elements
my_list[0] = 100
print(f"List after modifying first element: {my_list}") # Output: [100, 2, 3, 'apple', 'banana', True]

# Adding elements
my_list.append("cherry") # Adds to the end
print(f"List after appending: {my_list}") # Output: [100, 2, 3, 'apple', 'banana', True, 'cherry']
my_list.insert(1, "orange") # Inserts at a specific index
print(f"List after inserting at index 1: {my_list}") # Output: [100, 'orange', 2, 3, 'apple', 'banana', True, 'cherry']

# Removing elements
my_list.remove("apple") # Removes the first occurrence of a value
print(f"List after removing 'apple': {my_list}") # Output: [100, 'orange', 2, 3, 'banana', True, 'cherry']
popped_item = my_list.pop(0) # Removes and returns element at specific index (or last if no index given)
print(f"List after popping element at index 0: {my_list}") # Output: ['orange', 2, 3, 'banana', True, 'cherry']
print(f"Popped item: {popped_item}") # Output: 100

Key points
- Lists are created using square brackets `[]`.
- They can hold items of different data types.
- Lists are **ordered**, meaning items have a defined sequence.
- Lists are **mutable**, meaning you can change, add, or remove elements after creation.
- Elements are accessed using **zero-based indexing** (the first element is at index 0).
- Methods like `append()`, `insert()`, `remove()`, and `pop()` are used to modify lists.

Practice work
1. Create a Python list named `fruits` containing "apple", "banana", "orange".
2. Add "grape" to the end of the `fruits` list.
3. Insert "strawberry" at the second position (index 1) in the `fruits` list.
4. Change "banana" to "kiwi" in the `fruits` list.
5. Print the final `fruits` list.

Knowledge check
1. What distinguishes a list from a simple variable in Python?
2. How do you access the fifth element of a list named `my_data`?
3. If you want to add an item to the very end of a list, which method would you use?
4. True or False: Once a list is created, its size cannot be changed.

Section 2 - Python Loops: Automating Repetitive Tasks
Summary Loops are control flow statements that allow you to execute a block of code multiple times. They are fundamental for automating repetitive tasks. Python primarily provides two types of loops: `for` loops, used for iterating over a sequence (like a list) or other iterable objects, and `while` loops, which continue to execute as long as a certain condition is true.

Data
# For loop: Iterating through a list
print("Using a for loop to print list items:")
my_numbers = [10, 20, 30, 40, 50]
for number in my_numbers:
    print(number)

# For loop with range(): Iterating a specific number of times
print("\nUsing a for loop with range(3):")
for i in range(3): # range(3) generates numbers 0, 1, 2
    print(f"Iteration {i}")

# For loop with range() for list indices
print("\nUsing a for loop with range(len(my_numbers)) to access by index:")
for i in range(len(my_numbers)):
    print(f"Element at index {i}: {my_numbers[i]}")

# While loop: Executing as long as a condition is true
print("\nUsing a while loop:")
count = 0
while count < 5:
    print(f"Count is {count}")
    count += 1 # Increment count to eventually stop the loop

# While loop with break
print("\nUsing a while loop with break:")
secret_number = 7
guess = 0
while True: # Infinite loop until 'break' is encountered
    guess += 1
    if guess == secret_number:
        print(f"Found the secret number: {secret_number} in {guess} guesses!")
        break # Exits the loop

Key points
- `for` loops are used for definite iteration (when you know how many times to repeat).
- `while` loops are used for indefinite iteration (when the number of repetitions depends on a condition).
- Indentation (typically 4 spaces) is crucial in Python to define the code block within a loop.
- The `range()` function is often used with `for` loops to generate a sequence of numbers.
- `break` statement can be used to exit a loop prematurely.
- `continue` statement skips the rest of the current loop iteration and moves to the next.

Practice work
1. Create a list of strings: `colors = ["red", "green", "blue"]`.
2. Use a `for` loop to print each color in the `colors` list, prefixed with "My favorite color is: ".
3. Use a `while` loop to count down from 5 to 1, printing each number. After 1, print "Blastoff!".

Knowledge check
1. When would you typically use a `for` loop instead of a `while` loop?
2. What is the purpose of the `range()` function when used with a `for` loop?
3. Explain the importance of indentation in Python loops.
4. How would you stop a `while` loop from continuing forever if its condition always evaluates to `True`?