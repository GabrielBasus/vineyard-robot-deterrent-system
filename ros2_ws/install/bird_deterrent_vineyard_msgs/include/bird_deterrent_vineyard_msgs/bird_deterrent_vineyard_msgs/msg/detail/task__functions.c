// generated from rosidl_generator_c/resource/idl__functions.c.em
// with input from bird_deterrent_vineyard_msgs:msg/Task.idl
// generated code does not contain a copyright notice
#include "bird_deterrent_vineyard_msgs/msg/detail/task__functions.h"

#include <assert.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#include "rcutils/allocator.h"


// Include directives for member types
// Member `id`
// Member `type`
// Member `assigned_primary`
// Member `assigned_secondary`
#include "rosidl_runtime_c/string_functions.h"

bool
bird_deterrent_vineyard_msgs__msg__Task__init(bird_deterrent_vineyard_msgs__msg__Task * msg)
{
  if (!msg) {
    return false;
  }
  // id
  if (!rosidl_runtime_c__String__init(&msg->id)) {
    bird_deterrent_vineyard_msgs__msg__Task__fini(msg);
    return false;
  }
  // type
  if (!rosidl_runtime_c__String__init(&msg->type)) {
    bird_deterrent_vineyard_msgs__msg__Task__fini(msg);
    return false;
  }
  // x
  // y
  // time
  // assigned_primary
  if (!rosidl_runtime_c__String__init(&msg->assigned_primary)) {
    bird_deterrent_vineyard_msgs__msg__Task__fini(msg);
    return false;
  }
  // assigned_secondary
  if (!rosidl_runtime_c__String__init(&msg->assigned_secondary)) {
    bird_deterrent_vineyard_msgs__msg__Task__fini(msg);
    return false;
  }
  // score
  return true;
}

void
bird_deterrent_vineyard_msgs__msg__Task__fini(bird_deterrent_vineyard_msgs__msg__Task * msg)
{
  if (!msg) {
    return;
  }
  // id
  rosidl_runtime_c__String__fini(&msg->id);
  // type
  rosidl_runtime_c__String__fini(&msg->type);
  // x
  // y
  // time
  // assigned_primary
  rosidl_runtime_c__String__fini(&msg->assigned_primary);
  // assigned_secondary
  rosidl_runtime_c__String__fini(&msg->assigned_secondary);
  // score
}

bool
bird_deterrent_vineyard_msgs__msg__Task__are_equal(const bird_deterrent_vineyard_msgs__msg__Task * lhs, const bird_deterrent_vineyard_msgs__msg__Task * rhs)
{
  if (!lhs || !rhs) {
    return false;
  }
  // id
  if (!rosidl_runtime_c__String__are_equal(
      &(lhs->id), &(rhs->id)))
  {
    return false;
  }
  // type
  if (!rosidl_runtime_c__String__are_equal(
      &(lhs->type), &(rhs->type)))
  {
    return false;
  }
  // x
  if (lhs->x != rhs->x) {
    return false;
  }
  // y
  if (lhs->y != rhs->y) {
    return false;
  }
  // time
  if (lhs->time != rhs->time) {
    return false;
  }
  // assigned_primary
  if (!rosidl_runtime_c__String__are_equal(
      &(lhs->assigned_primary), &(rhs->assigned_primary)))
  {
    return false;
  }
  // assigned_secondary
  if (!rosidl_runtime_c__String__are_equal(
      &(lhs->assigned_secondary), &(rhs->assigned_secondary)))
  {
    return false;
  }
  // score
  if (lhs->score != rhs->score) {
    return false;
  }
  return true;
}

bool
bird_deterrent_vineyard_msgs__msg__Task__copy(
  const bird_deterrent_vineyard_msgs__msg__Task * input,
  bird_deterrent_vineyard_msgs__msg__Task * output)
{
  if (!input || !output) {
    return false;
  }
  // id
  if (!rosidl_runtime_c__String__copy(
      &(input->id), &(output->id)))
  {
    return false;
  }
  // type
  if (!rosidl_runtime_c__String__copy(
      &(input->type), &(output->type)))
  {
    return false;
  }
  // x
  output->x = input->x;
  // y
  output->y = input->y;
  // time
  output->time = input->time;
  // assigned_primary
  if (!rosidl_runtime_c__String__copy(
      &(input->assigned_primary), &(output->assigned_primary)))
  {
    return false;
  }
  // assigned_secondary
  if (!rosidl_runtime_c__String__copy(
      &(input->assigned_secondary), &(output->assigned_secondary)))
  {
    return false;
  }
  // score
  output->score = input->score;
  return true;
}

bird_deterrent_vineyard_msgs__msg__Task *
bird_deterrent_vineyard_msgs__msg__Task__create()
{
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  bird_deterrent_vineyard_msgs__msg__Task * msg = (bird_deterrent_vineyard_msgs__msg__Task *)allocator.allocate(sizeof(bird_deterrent_vineyard_msgs__msg__Task), allocator.state);
  if (!msg) {
    return NULL;
  }
  memset(msg, 0, sizeof(bird_deterrent_vineyard_msgs__msg__Task));
  bool success = bird_deterrent_vineyard_msgs__msg__Task__init(msg);
  if (!success) {
    allocator.deallocate(msg, allocator.state);
    return NULL;
  }
  return msg;
}

void
bird_deterrent_vineyard_msgs__msg__Task__destroy(bird_deterrent_vineyard_msgs__msg__Task * msg)
{
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  if (msg) {
    bird_deterrent_vineyard_msgs__msg__Task__fini(msg);
  }
  allocator.deallocate(msg, allocator.state);
}


bool
bird_deterrent_vineyard_msgs__msg__Task__Sequence__init(bird_deterrent_vineyard_msgs__msg__Task__Sequence * array, size_t size)
{
  if (!array) {
    return false;
  }
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  bird_deterrent_vineyard_msgs__msg__Task * data = NULL;

  if (size) {
    data = (bird_deterrent_vineyard_msgs__msg__Task *)allocator.zero_allocate(size, sizeof(bird_deterrent_vineyard_msgs__msg__Task), allocator.state);
    if (!data) {
      return false;
    }
    // initialize all array elements
    size_t i;
    for (i = 0; i < size; ++i) {
      bool success = bird_deterrent_vineyard_msgs__msg__Task__init(&data[i]);
      if (!success) {
        break;
      }
    }
    if (i < size) {
      // if initialization failed finalize the already initialized array elements
      for (; i > 0; --i) {
        bird_deterrent_vineyard_msgs__msg__Task__fini(&data[i - 1]);
      }
      allocator.deallocate(data, allocator.state);
      return false;
    }
  }
  array->data = data;
  array->size = size;
  array->capacity = size;
  return true;
}

void
bird_deterrent_vineyard_msgs__msg__Task__Sequence__fini(bird_deterrent_vineyard_msgs__msg__Task__Sequence * array)
{
  if (!array) {
    return;
  }
  rcutils_allocator_t allocator = rcutils_get_default_allocator();

  if (array->data) {
    // ensure that data and capacity values are consistent
    assert(array->capacity > 0);
    // finalize all array elements
    for (size_t i = 0; i < array->capacity; ++i) {
      bird_deterrent_vineyard_msgs__msg__Task__fini(&array->data[i]);
    }
    allocator.deallocate(array->data, allocator.state);
    array->data = NULL;
    array->size = 0;
    array->capacity = 0;
  } else {
    // ensure that data, size, and capacity values are consistent
    assert(0 == array->size);
    assert(0 == array->capacity);
  }
}

bird_deterrent_vineyard_msgs__msg__Task__Sequence *
bird_deterrent_vineyard_msgs__msg__Task__Sequence__create(size_t size)
{
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  bird_deterrent_vineyard_msgs__msg__Task__Sequence * array = (bird_deterrent_vineyard_msgs__msg__Task__Sequence *)allocator.allocate(sizeof(bird_deterrent_vineyard_msgs__msg__Task__Sequence), allocator.state);
  if (!array) {
    return NULL;
  }
  bool success = bird_deterrent_vineyard_msgs__msg__Task__Sequence__init(array, size);
  if (!success) {
    allocator.deallocate(array, allocator.state);
    return NULL;
  }
  return array;
}

void
bird_deterrent_vineyard_msgs__msg__Task__Sequence__destroy(bird_deterrent_vineyard_msgs__msg__Task__Sequence * array)
{
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  if (array) {
    bird_deterrent_vineyard_msgs__msg__Task__Sequence__fini(array);
  }
  allocator.deallocate(array, allocator.state);
}

bool
bird_deterrent_vineyard_msgs__msg__Task__Sequence__are_equal(const bird_deterrent_vineyard_msgs__msg__Task__Sequence * lhs, const bird_deterrent_vineyard_msgs__msg__Task__Sequence * rhs)
{
  if (!lhs || !rhs) {
    return false;
  }
  if (lhs->size != rhs->size) {
    return false;
  }
  for (size_t i = 0; i < lhs->size; ++i) {
    if (!bird_deterrent_vineyard_msgs__msg__Task__are_equal(&(lhs->data[i]), &(rhs->data[i]))) {
      return false;
    }
  }
  return true;
}

bool
bird_deterrent_vineyard_msgs__msg__Task__Sequence__copy(
  const bird_deterrent_vineyard_msgs__msg__Task__Sequence * input,
  bird_deterrent_vineyard_msgs__msg__Task__Sequence * output)
{
  if (!input || !output) {
    return false;
  }
  if (output->capacity < input->size) {
    const size_t allocation_size =
      input->size * sizeof(bird_deterrent_vineyard_msgs__msg__Task);
    rcutils_allocator_t allocator = rcutils_get_default_allocator();
    bird_deterrent_vineyard_msgs__msg__Task * data =
      (bird_deterrent_vineyard_msgs__msg__Task *)allocator.reallocate(
      output->data, allocation_size, allocator.state);
    if (!data) {
      return false;
    }
    // If reallocation succeeded, memory may or may not have been moved
    // to fulfill the allocation request, invalidating output->data.
    output->data = data;
    for (size_t i = output->capacity; i < input->size; ++i) {
      if (!bird_deterrent_vineyard_msgs__msg__Task__init(&output->data[i])) {
        // If initialization of any new item fails, roll back
        // all previously initialized items. Existing items
        // in output are to be left unmodified.
        for (; i-- > output->capacity; ) {
          bird_deterrent_vineyard_msgs__msg__Task__fini(&output->data[i]);
        }
        return false;
      }
    }
    output->capacity = input->size;
  }
  output->size = input->size;
  for (size_t i = 0; i < input->size; ++i) {
    if (!bird_deterrent_vineyard_msgs__msg__Task__copy(
        &(input->data[i]), &(output->data[i])))
    {
      return false;
    }
  }
  return true;
}
