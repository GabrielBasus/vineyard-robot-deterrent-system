// generated from rosidl_generator_cpp/resource/idl__struct.hpp.em
// with input from bird_deterrent_vineyard_msgs:msg/TaskStatus.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK_STATUS__STRUCT_HPP_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK_STATUS__STRUCT_HPP_

#include <algorithm>
#include <array>
#include <memory>
#include <string>
#include <vector>

#include "rosidl_runtime_cpp/bounded_vector.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


#ifndef _WIN32
# define DEPRECATED__bird_deterrent_vineyard_msgs__msg__TaskStatus __attribute__((deprecated))
#else
# define DEPRECATED__bird_deterrent_vineyard_msgs__msg__TaskStatus __declspec(deprecated)
#endif

namespace bird_deterrent_vineyard_msgs
{

namespace msg
{

// message struct
template<class ContainerAllocator>
struct TaskStatus_
{
  using Type = TaskStatus_<ContainerAllocator>;

  explicit TaskStatus_(rosidl_runtime_cpp::MessageInitialization _init = rosidl_runtime_cpp::MessageInitialization::ALL)
  {
    if (rosidl_runtime_cpp::MessageInitialization::ALL == _init ||
      rosidl_runtime_cpp::MessageInitialization::ZERO == _init)
    {
      this->t = 0.0;
      this->event = "";
      this->robot_id = "";
      this->task_id = "";
      this->type = "";
      this->x = 0.0;
      this->y = 0.0;
      this->role = "";
      this->extra = "";
    }
  }

  explicit TaskStatus_(const ContainerAllocator & _alloc, rosidl_runtime_cpp::MessageInitialization _init = rosidl_runtime_cpp::MessageInitialization::ALL)
  : event(_alloc),
    robot_id(_alloc),
    task_id(_alloc),
    type(_alloc),
    role(_alloc),
    extra(_alloc)
  {
    if (rosidl_runtime_cpp::MessageInitialization::ALL == _init ||
      rosidl_runtime_cpp::MessageInitialization::ZERO == _init)
    {
      this->t = 0.0;
      this->event = "";
      this->robot_id = "";
      this->task_id = "";
      this->type = "";
      this->x = 0.0;
      this->y = 0.0;
      this->role = "";
      this->extra = "";
    }
  }

  // field types and members
  using _t_type =
    double;
  _t_type t;
  using _event_type =
    std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>>;
  _event_type event;
  using _robot_id_type =
    std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>>;
  _robot_id_type robot_id;
  using _task_id_type =
    std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>>;
  _task_id_type task_id;
  using _type_type =
    std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>>;
  _type_type type;
  using _x_type =
    double;
  _x_type x;
  using _y_type =
    double;
  _y_type y;
  using _role_type =
    std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>>;
  _role_type role;
  using _extra_type =
    std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>>;
  _extra_type extra;

  // setters for named parameter idiom
  Type & set__t(
    const double & _arg)
  {
    this->t = _arg;
    return *this;
  }
  Type & set__event(
    const std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>> & _arg)
  {
    this->event = _arg;
    return *this;
  }
  Type & set__robot_id(
    const std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>> & _arg)
  {
    this->robot_id = _arg;
    return *this;
  }
  Type & set__task_id(
    const std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>> & _arg)
  {
    this->task_id = _arg;
    return *this;
  }
  Type & set__type(
    const std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>> & _arg)
  {
    this->type = _arg;
    return *this;
  }
  Type & set__x(
    const double & _arg)
  {
    this->x = _arg;
    return *this;
  }
  Type & set__y(
    const double & _arg)
  {
    this->y = _arg;
    return *this;
  }
  Type & set__role(
    const std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>> & _arg)
  {
    this->role = _arg;
    return *this;
  }
  Type & set__extra(
    const std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>> & _arg)
  {
    this->extra = _arg;
    return *this;
  }

  // constant declarations

  // pointer types
  using RawPtr =
    bird_deterrent_vineyard_msgs::msg::TaskStatus_<ContainerAllocator> *;
  using ConstRawPtr =
    const bird_deterrent_vineyard_msgs::msg::TaskStatus_<ContainerAllocator> *;
  using SharedPtr =
    std::shared_ptr<bird_deterrent_vineyard_msgs::msg::TaskStatus_<ContainerAllocator>>;
  using ConstSharedPtr =
    std::shared_ptr<bird_deterrent_vineyard_msgs::msg::TaskStatus_<ContainerAllocator> const>;

  template<typename Deleter = std::default_delete<
      bird_deterrent_vineyard_msgs::msg::TaskStatus_<ContainerAllocator>>>
  using UniquePtrWithDeleter =
    std::unique_ptr<bird_deterrent_vineyard_msgs::msg::TaskStatus_<ContainerAllocator>, Deleter>;

  using UniquePtr = UniquePtrWithDeleter<>;

  template<typename Deleter = std::default_delete<
      bird_deterrent_vineyard_msgs::msg::TaskStatus_<ContainerAllocator>>>
  using ConstUniquePtrWithDeleter =
    std::unique_ptr<bird_deterrent_vineyard_msgs::msg::TaskStatus_<ContainerAllocator> const, Deleter>;
  using ConstUniquePtr = ConstUniquePtrWithDeleter<>;

  using WeakPtr =
    std::weak_ptr<bird_deterrent_vineyard_msgs::msg::TaskStatus_<ContainerAllocator>>;
  using ConstWeakPtr =
    std::weak_ptr<bird_deterrent_vineyard_msgs::msg::TaskStatus_<ContainerAllocator> const>;

  // pointer types similar to ROS 1, use SharedPtr / ConstSharedPtr instead
  // NOTE: Can't use 'using' here because GNU C++ can't parse attributes properly
  typedef DEPRECATED__bird_deterrent_vineyard_msgs__msg__TaskStatus
    std::shared_ptr<bird_deterrent_vineyard_msgs::msg::TaskStatus_<ContainerAllocator>>
    Ptr;
  typedef DEPRECATED__bird_deterrent_vineyard_msgs__msg__TaskStatus
    std::shared_ptr<bird_deterrent_vineyard_msgs::msg::TaskStatus_<ContainerAllocator> const>
    ConstPtr;

  // comparison operators
  bool operator==(const TaskStatus_ & other) const
  {
    if (this->t != other.t) {
      return false;
    }
    if (this->event != other.event) {
      return false;
    }
    if (this->robot_id != other.robot_id) {
      return false;
    }
    if (this->task_id != other.task_id) {
      return false;
    }
    if (this->type != other.type) {
      return false;
    }
    if (this->x != other.x) {
      return false;
    }
    if (this->y != other.y) {
      return false;
    }
    if (this->role != other.role) {
      return false;
    }
    if (this->extra != other.extra) {
      return false;
    }
    return true;
  }
  bool operator!=(const TaskStatus_ & other) const
  {
    return !this->operator==(other);
  }
};  // struct TaskStatus_

// alias to use template instance with default allocator
using TaskStatus =
  bird_deterrent_vineyard_msgs::msg::TaskStatus_<std::allocator<void>>;

// constant definitions

}  // namespace msg

}  // namespace bird_deterrent_vineyard_msgs

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK_STATUS__STRUCT_HPP_
